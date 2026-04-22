source("R/index.r")

index.set=function(ofn, descriptions.ifn, table.ifn, dyn.vars, mount.dirs, output.bucket, on.missing.file, max.items=0, ...)
{
    vars = list(...)
    df = load.table(table.ifn)
    # already vectors from R_call.r parsing

    missing.cols = setdiff(dyn.vars, colnames(df))
    if (length(missing.cols) > 0)
        stop(sprintf("dyn.vars not found in table: %s", paste(missing.cols, collapse=", ")))
    df = as.data.frame(df[, dyn.vars, drop=F])

    if (max.items > 0) df = df[seq_len(min(max.items, nrow(df))), , drop=F]
    cat(sprintf("indexing %d variable(s) x %d %s(s)\n",
                length(vars), nrow(df), paste(dyn.vars, collapse="/")))

    descriptions = load.descriptions(descriptions.ifn, names(vars))

    # build class table: one row per variable, path template with {KEY} placeholders
    tag.keys = paste(dyn.vars, collapse=":")
    rr.class = NULL
    for (i in seq_along(vars)) {
        var.name = names(vars)[i]
        tmpl = tryCatch(
            translate.path(vars[[i]], mount.dirs, output.bucket),
            error = function(e) {
                if (on.missing.file == "error") stop(e$message)
                vars[[i]]
            }
        )
        for (dv in dyn.vars)
            tmpl = gsub(dv, sprintf("{%s}", dv), tmpl, fixed=T)
        rr.class = rbind(rr.class, data.frame(variable=var.name, tag_keys=tag.keys,
                                              description=descriptions[[var.name]],
                                              path_template=tmpl, stringsAsFactors=F))
    }

    # build instance table: one row per variable x row
    rr.instance = NULL
    for (k in seq_len(nrow(df))) {
        row = df[k, , drop=F]
        tag = paste(paste0(dyn.vars, "=", unlist(row)), collapse=":")

        for (i in seq_along(vars)) {
            var.name = names(vars)[i]
            src = vars[[i]]
            for (j in seq_along(dyn.vars)) {
                src = gsub(dyn.vars[j], as.character(row[[dyn.vars[j]]]), src, fixed=T)
            }
            gs.path = tryCatch(
                translate.path(src, mount.dirs, output.bucket),
                error = function(e) {
                    if (on.missing.file == "error") stop(e$message)
                    cat(sprintf("  warning: %s\n", e$message))
                    NA_character_
                }
            )
            size  = 0
            found = F
            if (!is.na(gs.path) && grepl("^gs://", gs.path)) {
                size = gsutil.size(gs.path)
                found = size > 0
                if (found)
                    cat(sprintf("  [%d/%d] %-30s %-30s %.1f Mb\n", k, nrow(df), var.name, tag, size/1e6))
                else {
                    if (on.missing.file == "error")
                        stop(sprintf("missing: %s [%s] -> %s", var.name, tag, gs.path))
                    cat(sprintf("  [%d/%d] %-30s %-30s missing\n", k, nrow(df), var.name, tag))
                }
            }
            rr.instance = rbind(rr.instance, data.frame(variable=var.name, tag=tag,
                                                        path=ifelse(is.na(gs.path), src, gs.path),
                                                        size=size, found=found,
                                                        stringsAsFactors=F))
        }
    }

    cat(sprintf("done: %d/%d found, total %.1f Mb\n", sum(rr.instance$found), nrow(rr.instance),
                sum(rr.instance$size)/1e6))
    save.table(rr.class,    class.ofn(ofn))
    save.table(rr.instance, ofn)
}
