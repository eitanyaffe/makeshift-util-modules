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
                    on.missing.file, external.dir, mount.dirs, config.dir,
                    select.aids="all", exclude.aids="none", export.tag="default", ...)
{
    df = load.table(table.ifn)
    
    # apply assembly selection filter
    if (!(length(select.aids) == 1 && select.aids[1] == "all")) {
        aids = as.character(select.aids)
        cat(sprintf("selecting assembly ids: %s\n", paste(aids, collapse=" ")))
        if (!"ASSEMBLY_ID" %in% colnames(df))
            stop("assembly selection requires ASSEMBLY_ID column")
        missing = setdiff(aids, unique(df$ASSEMBLY_ID))
        if (length(missing) > 0)
            stop(sprintf("missing assembly ids: %s", paste(missing, collapse=" ")))
        df = df[df$ASSEMBLY_ID %in% aids,,drop=F]
        if (dim(df)[1] == 0)
            stop("no assemblies left after selection")
    }
    
    # apply assembly exclusion filter
    if (!(length(exclude.aids) == 1 && exclude.aids[1] == "none")) {
        exclude.ids = as.character(exclude.aids)
        cat(sprintf("excluding assembly ids: %s\n", paste(exclude.ids, collapse=" ")))
        if (!"ASSEMBLY_ID" %in% colnames(df))
            stop("assembly exclusion requires ASSEMBLY_ID column")
        df = df[!df$ASSEMBLY_ID %in% exclude.ids,,drop=F]
        if (dim(df)[1] == 0) {
            cat("no assemblies left after exclusion\n")
            save.table(data.frame(id=character(0), found=logical(0), path=character(0)), ofn)
            return()
        }
    }
    
    cat(sprintf("number of %s items to export: %d\n", export.tag, dim(df)[1]))
    
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
