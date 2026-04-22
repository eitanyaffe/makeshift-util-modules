
index.combine=function(modules, module.dirs, odir, summary.ofn)
{
    if (length(modules) != length(module.dirs))
        stop(sprintf("INDEX_MODULES (%d) and INDEX_MODULE_DIRS (%d) must have the same length",
                     length(modules), length(module.dirs)))

    dir.create(odir, recursive=T, showWarnings=F)

    all.instances = NULL
    all.class     = NULL
    summary       = NULL

    for (i in seq_along(modules)) {
        mod           = modules[i]
        mod.index.dir = module.dirs[i]

        if (!dir.exists(mod.index.dir)) {
            cat(sprintf("warning: index dir not found for module %s: %s\n", mod, mod.index.dir))
            next
        }

        files = list.files(mod.index.dir, pattern="\\.txt$", full.names=T)
        if (length(files) == 0) {
            cat(sprintf("warning: no index tables found for module %s in %s\n", mod, mod.index.dir))
            next
        }

        n.vars     = 0
        total.size = 0
        for (f in files) {
            tbl = load.table(f)
            tbl = cbind(data.frame(module=mod, stringsAsFactors=F), tbl)

            if (grepl("\\.class\\.txt$", f)) {
                all.class = rbind(all.class, tbl)
            } else {
                if ("variable" %in% colnames(tbl))
                    n.vars = n.vars + length(unique(tbl$variable))
                if ("size" %in% colnames(tbl))
                    total.size = total.size + sum(tbl$size, na.rm=T)
                all.instances = rbind(all.instances, tbl)
            }
            cat(sprintf("  %s: %d rows\n", basename(f), nrow(tbl)))
        }

        summary = rbind(summary, data.frame(
            module        = mod,
            n_variables   = n.vars,
            total_size_gb = round(total.size / 1e9, 3),
            stringsAsFactors = F
        ))
    }

    if (is.null(summary)) {
        cat("warning: no modules were indexed\n")
        summary = data.frame(module=character(0), n_variables=integer(0), total_size_gb=numeric(0))
    }

    save.table(summary,                              summary.ofn)
    save.table(all.instances,                        file.path(odir, "all.txt"))
    if (!is.null(all.class))
        save.table(all.class,                        file.path(odir, "all_class.txt"))

    cat(sprintf("\nindex summary (%d modules):\n", nrow(summary)))
    for (i in seq_len(nrow(summary)))
        cat(sprintf("  %-20s  vars: %4d  size: %.3f GB\n",
                    summary$module[i], summary$n_variables[i], summary$total_size_gb[i]))
}
