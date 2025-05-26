create.table=function(df, vars, external.dir, mount.dirs, config.dir, odir)
{
    rr = NULL
    for (k in 1:dim(df)[1]) {
        instance=function(fn, dfx) {
            for (j in 1:dim(dfx)[2]) {
                fn = gsub(colnames(dfx)[j], dfx[j], fn)
            }
            fn
        }
        for (i in 1:length(vars)) {
            name = names(vars)[i]
            dfx = as.data.frame(df[k,])
            colnames(dfx) = colnames(df)
            src = instance(vars[[i]], dfx)
            found = F
            for (mount.dir in mount.dirs) {
                if (grepl(mount.dir, src)) {
                    tgt = gsub(mount.dir, odir, src)
                    path = gsub(mount.dir, external.dir, src)
                    found = T
                    break
                }
            }
            if (!found) {
                if (grepl(config.dir, src)) {
                    tgt = gsub(config.dir, paste0(odir, "/config"), src)
                    path = gsub(config.dir,paste0(external.dir, "/config"), src)
                } else {
                    stop(sprintf("path does not contain output or config mount directories: %s\n", src))
                }
            }
            id = paste0(name, ":", paste(df[k,], collapse="_"))
            rr = rbind(rr, data.frame(id=id, src=src, tgt=tgt, path=path))
        }
    }
    rr
}

export.set=function(table.ifn, dyn.vars, ofn, odir,
                    on.missing.file, external.dir, mount.dirs, config.dir, ...)
{
    df = load.table(table.ifn)
    df = as.data.frame(df[,dyn.vars])
    colnames(df) = dyn.vars
    
    vars = list(...)
    rr = create.table(df=df, vars=vars, external.dir=external.dir,
                      mount.dirs=mount.dirs, config.dir=config.dir, odir=odir)
    rr$size = 0
    rr$found = F

    cat("computing total size ...\n")
    for (i in 1:dim(rr)[1]) {
        ifn = rr$src[i]
        if (file.exists(ifn)) {
            rr$size[i] = file.info(ifn)$size
        }
    }
    cat(sprintf("total export number of files: %d\n", sum(rr$size != 0)))
    cat(sprintf("total export size: %.1fG\n", sum(rr$size)/10^9))
    
    cat(sprintf("exporting files to directory: %s\n", odir))
    for (i in 1:dim(rr)[1]) {
        name = rr$id[i]
        ifn = rr$src[i]
        ofn.i = rr$tgt[i]
        size = rr$size[i]

        if (ifn == ofn.i)
            stop(sprintf("ifn and ofn identical: %s\n", ifn))

        if (!file.exists(ifn)) {
            if (on.missing.file == "error")
                stop(sprintf("Missing file: %s", ifn))
            else
                cat(sprintf("Warning: skipping %s, missing file: %s\n", name, ifn))
            next
        }
        rr$found[i] = T
        command = sprintf("mkdir -p %s", dirname(ofn.i))
        if (system(command) != 0)
            stop(paste("failed command:", command))
            
        command = sprintf("rsync -r -t %s %s", ifn, ofn.i)
        #cat(sprintf("syncing %s (%.1fMb): %s\n", name, size/10^6, command))
        cat(sprintf("syncing %s (%.1fMb) : %s\n", name, size/10^6, ifn))
        if (system(command) != 0)
            stop(paste("failed command:", command))
    }

    save.table(rr[,c("id", "found", "path")], ofn)

    cat(sprintf("NOTE: Downloaded files can be accessed outside the environment on %s\n", external.dir))
}
