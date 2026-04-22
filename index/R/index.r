
# translate a local output-mount path to its gs:// equivalent
translate.path=function(src, mount.dirs, output.bucket)
{
    for (mount.dir in mount.dirs) {
        if (grepl(mount.dir, src, fixed=T)) {
            return(sub(mount.dir, output.bucket, src, fixed=T))
        }
    }
    stop(sprintf("path does not match output mount dir: %s", src))
}

# get size in bytes for a single gs:// path; returns 0 if not found
gsutil.size=function(path)
{
    cmd = sprintf("gsutil du -s %s 2>/dev/null", path)
    lines = system(cmd, intern=T)
    if (length(lines) == 0)
        return(0)
    parts = strsplit(trimws(lines[1]), "\\s+")[[1]]
    if (length(parts) < 2)
        return(0)
    bytes = suppressWarnings(as.numeric(parts[1]))
    if (is.na(bytes)) 0 else bytes
}

# class file ofn derived from instance ofn
class.ofn=function(ofn) sub("\\.txt$", ".class.txt", ofn)

# load variable descriptions from a json file; error if file missing or any var has no entry
load.descriptions=function(ifn, vars)
{
    library(jsonlite)
    if (!file.exists(ifn))
        stop(sprintf("descriptions json not found: %s", ifn))
    dd = fromJSON(ifn, simplifyVector=T)
    if (!is.list(dd) || is.null(names(dd)))
        stop(sprintf("descriptions json must be a flat name->string map: %s", ifn))
    missing.keys = setdiff(vars, names(dd))
    if (length(missing.keys) > 0)
        stop(sprintf("missing descriptions in %s: %s", ifn, paste(missing.keys, collapse=", ")))
    unlist(dd[vars])
}

index.table=function(ofn, descriptions.ifn, mount.dirs, output.bucket, on.missing.file, max.items=0, ...)
{
    vars = list(...)
    # already a vector from R_call.r parsing

    if (max.items > 0) vars = vars[seq_len(min(max.items, length(vars)))]
    cat(sprintf("indexing %d global variable(s)\n", length(vars)))

    descriptions = load.descriptions(descriptions.ifn, names(vars))

    rr.class    = NULL
    rr.instance = NULL

    for (i in seq_along(vars)) {
        var.name = names(vars)[i]
        src = vars[[i]]
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
                cat(sprintf("  %-40s %.1f Mb\n", var.name, size/1e6))
            else {
                if (on.missing.file == "error")
                    stop(sprintf("missing: %s -> %s", var.name, gs.path))
                cat(sprintf("  %-40s missing\n", var.name))
            }
        }
        path.val = ifelse(is.na(gs.path), src, gs.path)
        rr.class    = rbind(rr.class,    data.frame(variable=var.name, tag_keys="global",
                                                    description=descriptions[[var.name]],
                                                    path_template=path.val, stringsAsFactors=F))
        rr.instance = rbind(rr.instance, data.frame(variable=var.name, tag="global",
                                                    path=path.val, size=size, found=found,
                                                    stringsAsFactors=F))
    }

    cat(sprintf("done: %d/%d found, total %.1f Mb\n", sum(rr.instance$found), nrow(rr.instance),
                sum(rr.instance$size)/1e6))
    save.table(rr.class,    class.ofn(ofn))
    save.table(rr.instance, ofn)
}
