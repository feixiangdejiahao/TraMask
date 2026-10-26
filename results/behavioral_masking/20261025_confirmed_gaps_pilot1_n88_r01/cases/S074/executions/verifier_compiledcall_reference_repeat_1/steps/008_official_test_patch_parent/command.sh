python3 -I -c '
import os,sys
path=sys.argv[1];parent=os.path.dirname(path)
current='"'"'/'"'"'
for part in path.lstrip('"'"'/'"'"').split('"'"'/'"'"'):
    current=os.path.join(current,part)
    if os.path.islink(current):raise RuntimeError('"'"'copy_path_must_not_follow_symlink'"'"')
if os.path.isdir(path):raise RuntimeError('"'"'file_destination_is_directory'"'"')
os.makedirs(parent,exist_ok=True)
' /tmp/tramask-a1478ac18c374bba989a/test.patch