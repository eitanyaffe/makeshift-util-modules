
export.table=function(ofn, ...)
{
    vars = list(...)
    rr = NULL
    for (i in 1:length(vars)) {
        name = names(vars)[i]
        var = vars[[i]]
        rr = rbind(rr, data.frame(id=name, value=var))
    }
    save.table(rr, ofn)
}

####################################################################################
####################################################################################

create.table=function(vars, external.dir, mount.dir, odir)
{
    rr = NULL
    for (i in 1:length(vars)) {
        name = names(vars)[i]
        src = vars[[i]]
        tgt = gsub(mount.dir, odir, src)
        path = gsub(mount.dir, external.dir, src)
        rr = rbind(rr, data.frame(id=name, src=src, tgt=tgt, path=path))
    }
    rr
}

export.copy=function(ofn, odir, on.missing.file, external.dir, mount.dir, ...)
{
    vars = list(...)
    rr = create.table(vars=vars, external.dir=external.dir, mount.dir=mount.dir, odir=odir)
    rr$found = F
    
    cat(sprintf("exporting files to directory: %s\n", odir))
    for (i in 1:dim(rr)[1]) {
        name = rr$id[i]
        ifn = rr$src[i]
        ofn.i = rr$tgt[i]

        if (!file.exists(ifn)) {
            if (on.missing.file == "error")
                stop(sprintf("Missing file: %s", ifn))
            else
                cat(sprintf("Warning: skipping missing file: %s\n", ifn))
            next
        }
        rr$found[i] = T
        command = sprintf("mkdir -p %s", dirname(ofn.i))
        if (system(command) != 0)
            stop(paste("failed command:", command))
            
        command = sprintf("cp -r %s %s", ifn, ofn.i)
        cat(sprintf("copying %s: %s\n", name, command))
        if (system(command) != 0)
            stop(paste("failed command:", command))
    }

    save.table(rr[,c("id", "found", "path")], ofn)
}
