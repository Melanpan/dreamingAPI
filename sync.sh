#/bin/bash
rsync -avz --progress --delete --exclude '.git' --exclude 'run.sh' --exclude 'sync.sh' nurds@gpu.vm.nurd.space:~/dreamingAPI/ .