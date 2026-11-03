"""Observe one unchanged shell command on Linux/x86-64 using stdlib ptrace.

File bytes are captured while the tracee is stopped, including files removed
later in the same shell command. This records process/file provenance, not
statement execution or heap data flow. Run with SYS_PTRACE in Docker.
"""
import ctypes
from collections import deque
import errno
import importlib.util
import json
import marshal
import os
from pathlib import Path
import platform
import re
import signal
import stat
import struct
import sys
import time
import types

LIBC=ctypes.CDLL(None,use_errno=True)
LIBC.ptrace.restype=ctypes.c_long
TRACEME,SYSCALL,DETACH=0,24,17
SETOPTIONS,GETEVENTMSG,GETINFO=0x4200,0x4201,0x420e
OPTIONS=1|2|4|8|16|(1<<20)
READ={0,17,19};WRITE={1,18,20}
OPEN={2,257,437};EXEC={59,322}


def ptrace(request,pid,address=0,data=0):
    result=LIBC.ptrace(request,pid,ctypes.c_void_p(address),ctypes.c_void_p(data))
    if result==-1:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
    return result


class Recorder:
    def __init__(self,request,store_type):
        self.request=request;self.root=os.path.realpath(request['root'])
        self.directory=Path(request['trace_directory']);self.directory.mkdir()
        self.observer_root=str(self.directory.parent)
        self.store=store_type(self.directory/'blobs');self.store.create()
        self.log=(self.directory/'events.jsonl').open('w')
        self.count=0;self.pending={};self.activities={};self.file_cache={};self.uncacheable=set();self.bytecode_cache={};self.shared={}

    def event(self,kind,pid,**fields):
        row={'id':self.count,'kind':kind,'pid':pid,'execution':self.activities[pid],**fields}
        self.log.write(json.dumps(row,ensure_ascii=True)+'\n');self.count+=1
        return row['id']

    def blob(self,data):
        return self.store.put(data)

    def canonical(self,path):
        if path==self.root or path.startswith(self.root+'/'):return '/app'+path[len(self.root):]
        return path

    def memory(self,pid,address,length):
        with open(f'/proc/{pid}/mem','rb',buffering=0) as stream:
            return os.pread(stream.fileno(),length,address)

    def string(self,pid,address):
        if not address:return None
        result=b''
        while True:
            try:data=self.memory(pid,address+len(result),256)
            except OSError as error:
                if error.errno in {errno.EIO,errno.EFAULT}:return None
                raise
            if not data:return None
            if b'\0' in data:return (result+data.split(b'\0',1)[0]).decode(errors='surrogateescape')
            result+=data

    def argv(self,pid,address):
        result=[]
        while address:
            pointer,=struct.unpack('Q',self.memory(pid,address,8))
            if not pointer:break
            result.append(self.string(pid,pointer));address+=8
        return result

    def fd(self,pid,descriptor):
        link=f'/proc/{pid}/fd/{descriptor}'
        try:
            target=os.readlink(link)
            if target==self.request['output']:return {'channel':'stdout','observer':target}
            if target.startswith(self.observer_root+'/'):return {'observer':target}
            if target.startswith(('pipe:[','socket:[')):return {'channel':target}
            info=Path(f'/proc/{pid}/fdinfo/{descriptor}').read_text()
            position=int(next(line.split()[1] for line in info.splitlines() if line.startswith('pos:')))
            flags=int(next(line.split()[1] for line in info.splitlines() if line.startswith('flags:')),8)
            state=os.stat(link)
            if not stat.S_ISREG(state.st_mode) or target.startswith(('/proc/','/sys/')):
                return {'channel':target}
            identity=(state.st_dev,state.st_ino);stamp=(state.st_mtime_ns,state.st_ctime_ns,state.st_size)
            cached=self.file_cache.get(identity)
            fresh=identity in self.uncacheable or cached is None or cached[0]!=stamp
            if fresh:raw=Path(link).read_bytes()
        except FileNotFoundError:
            # Another tracee thread may close the descriptor during this stop.
            return None
        if fresh:
            digest=self.blob(raw)
            if identity not in self.uncacheable:self.file_cache[identity]=(stamp,digest)
        else:digest=cached[1]
        return {'version':{'path':self.canonical(target.removesuffix(' (deleted)')),
                           'sha256':digest,'bytes':state.st_size,'mode':stat.S_IMODE(state.st_mode),
                           'unlinked':target.endswith(' (deleted)')},'file_id':identity,
                'position':position,'append':bool(flags&os.O_APPEND)}

    def forget_path(self,path):
        if path is None or path.startswith(('/proc/','/sys/')):return
        try:state=os.stat(path)
        except FileNotFoundError:return
        self.file_cache.pop((state.st_dev,state.st_ino),None)

    def path(self,pid,address,dirfd=-100):
        text=self.string(pid,address)
        if text is None:return None
        if text.startswith('/'):return os.path.normpath(text)
        base=os.readlink(f'/proc/{pid}/cwd' if dirfd==-100 else f'/proc/{pid}/fd/{dirfd}')
        return os.path.normpath(os.path.join(base,text))

    def at_path(self,path):
        if path is not None and path.startswith(self.observer_root+'/'):return None
        if path is None or not os.path.isfile(path) or os.path.islink(path):return None
        if path.startswith(('/proc/','/sys/')):return None
        with open(path,'rb') as stream:
            state=os.fstat(stream.fileno())
            if not stat.S_ISREG(state.st_mode):return None
            raw=stream.read()
        return {'path':self.canonical(path),'sha256':self.blob(raw),'bytes':len(raw),
                'mode':stat.S_IMODE(state.st_mode),'unlinked':False}

    def data(self,pid,nr,args,count):
        if nr in {19,20}:
            result=[];remaining=count
            for index in range(args[2]):
                address,length=struct.unpack('QQ',self.memory(pid,args[1]+16*index,16))
                chunk=self.memory(pid,address,min(length,remaining));result.append(chunk);remaining-=len(chunk)
                if not remaining:break
            return b''.join(result)
        return self.memory(pid,args[1],count)

    def bytecode_source(self,version):
        if not version['path'].endswith('.pyc'):return None
        raw=self.store.read(version['sha256'])
        if raw[:4]!=importlib.util.MAGIC_NUMBER:
            path=version['path'];path=self.root+path[len('/app'):] if path.startswith('/app/') else path
            p=Path(path);name=p.name.split('.cpython-',1)[0]+'.py' if '__pycache__' in p.parts else p.name[:-1]
            source=self.at_path(str(p.parent.parent/name if '__pycache__' in p.parts else p.with_suffix('.py')))
            return {'version':source,'equivalent':False,'reason':'python_bytecode_version_differs'} if source is not None else {'reason':'bytecode_source_unavailable'}
        try:code=marshal.loads(raw[16:])
        except (EOFError,ValueError,TypeError) as error:return {'reason':'invalid_bytecode:'+str(error)}
        if not isinstance(code,types.CodeType):return {'reason':'not_python_code'}
        path=code.co_filename
        if not (path.startswith(self.root+'/') or path.startswith('/tmp/')):return None
        source=self.at_path(path)
        if source is None:return {'reason':'bytecode_source_unavailable'}
        key=version['sha256'],source['sha256']
        if key not in self.bytecode_cache:
            match=re.search(r'\.opt-([12])\.',version['path']);optimize=int(match[1]) if match else 0
            data=self.store.read(source['sha256'])
            try:equivalent=compile(data,code.co_filename,'exec',dont_inherit=True,optimize=optimize)==code
            except (SyntaxError,UnicodeError):equivalent=False
            self.bytecode_cache[key]=equivalent
        return {'version':source,'equivalent':self.bytecode_cache[key]}

    def enter(self,pid,nr,args):
        before=None;path=None;destination=None
        if nr in READ|WRITE|{3,9,77}:
            fd=args[4] if nr==9 else args[0]
            before=self.fd(pid,fd)
        if nr in OPEN|{76,82,87,90,257,263,264,316}:
            if nr in {257,263,264,316,437}:
                dirfd=ctypes.c_int(args[0]).value;path=self.path(pid,args[1],dirfd)
            else:path=self.path(pid,args[0])
            before=self.at_path(path)
            if nr==82:destination=self.path(pid,args[1])
            elif nr in {264,316}:destination=self.path(pid,args[3],ctypes.c_int(args[2]).value)
            if nr in OPEN|{76,82,87,263,264,316}:
                self.forget_path(path)
                if destination is not None:self.forget_path(destination)
        entry={'nr':nr,'args':args,'before':before,'path':path,'destination':destination}
        if nr in {40,326} or (nr==16 and args[1]==0x40049409):
            source=args[1] if nr==40 else args[0] if nr==326 else args[2]
            destination=args[0] if nr in {40,16} else args[2]
            entry.update(copy_source=self.fd(pid,source),copy_destination=self.fd(pid,destination),copy_fd=destination)
        if nr in EXEC:
            at=1 if nr==322 else 0
            entry['argv']=self.argv(pid,args[at+1])
            entry['program']=self.path(pid,args[at],ctypes.c_int(args[0]).value if nr==322 else -100)
            entry['environment']=self.blob(b'\0'.join(s.encode(errors='surrogateescape') for s in self.argv(pid,args[at+2])))
            entry['cwd']=self.canonical(os.readlink(f'/proc/{pid}/cwd'))
        if nr in {11,26,60,231}:
            for (owner,address,length),version in list(self.shared.items()):
                if owner!=pid or nr in {11,26} and not (args[0]<address+length and address<args[0]+args[1]):continue
                path=self.root+version['path'][len('/app'):] if version['path'].startswith('/app/') else version['path']
                after=self.at_path(path)
                if after is not None and after['sha256']!=version['sha256']:
                    self.event('file_change',pid,version=after,previous=version,basis='shared_mapping_observed')
                    self.shared[owner,address,length]=after
                if nr in {11,60,231}:self.shared.pop((owner,address,length))
        self.pending[pid]=entry

    def leave(self,pid,retval):
        item=self.pending.pop(pid,None)
        if item is None:return
        nr,args,before=item['nr'],item['args'],item['before']
        if retval<0:
            if nr in EXEC|OPEN|{76,77,82,87,263,264,316}:
                self.event('syscall_failed',pid,syscall=nr,returncode=retval,
                           path=self.canonical(item['path']) if item['path'] else None)
            return
        if nr in READ|WRITE and retval:
            if before is not None and 'observer' in before and (nr in READ or 'channel' not in before):
                self.event('observer_artifact_access',pid,path=before['observer'],syscall=nr,bytes=retval);return
            data=self.data(pid,nr,args,retval)
            if before is None:
                self.event('unresolved_io',pid,syscall=nr,descriptor=args[0],bytes=retval,data=self.blob(data));return
            if 'channel' in before:
                self.event('stream_read' if nr in READ else 'stream_write',pid,
                           channel=before['channel'],descriptor=args[0],data=self.blob(data),bytes=retval)
            else:
                offset=args[3] if nr in {17,18} else before['position']
                if nr in WRITE and before['append']:offset=before['version']['bytes']
                fields={'version':before['version'],'offset':offset,'bytes':retval,'data':self.blob(data)}
                if nr in WRITE:
                    self.file_cache.pop(before['file_id'],None)
                    after=self.fd(pid,args[0])
                    if after is None or 'version' not in after:
                        self.event('unresolved_file_write',pid,previous=before['version'],data=self.blob(data),bytes=retval);return
                    fields['previous']=before['version'];fields['version']=after['version']
                else:
                    matches=self.store.read_range(before['version']['sha256'],offset,retval)==data
                    fields['binding']='matches_read_bytes' if matches else 'concurrent_read_unresolved'
                    cache=self.bytecode_source(before['version'])
                    if cache is not None:fields['bytecode_source']=cache
                self.event('read' if nr in READ else 'write',pid,**fields)
        elif nr in OPEN:
            after=self.fd(pid,retval)
            if after and 'version' in after and before!=after['version']:
                self.event('file_open',pid,version=after['version'],previous=before)
        elif nr==9 and before and 'version' in before:
            cache=self.bytecode_source(before['version'])
            self.event('mapped',pid,version=before['version'],offset=args[5],bytes=args[1],bytecode_source=cache)
            if args[3]&1:
                self.uncacheable.add(before['file_id']);self.file_cache.pop(before['file_id'],None)
                self.shared[pid,retval,args[1]]=before['version']
        elif nr in {76,77,90}:
            if nr==77 and before and 'file_id' in before:self.file_cache.pop(before['file_id'],None)
            after=self.fd(pid,args[0])['version'] if nr==77 else self.at_path(item['path'])
            if after is None:
                self.event('metadata_change',pid,path=self.canonical(item['path']),mode=args[1],syscall=nr)
            else:self.event('file_change',pid,version=after,previous=before['version'] if nr==77 and before else before)
        elif nr in {87,263}:
            self.event('remove',pid,path=self.canonical(item['path']),previous=before)
        elif nr in {82,264,316}:
            self.event('rename',pid,path=self.canonical(item['path']),destination=self.canonical(item['destination']),
                       version=self.at_path(item['destination']),previous=before)
        elif 'copy_source' in item:
            source=item['copy_source'];before=item['copy_destination']
            if before and 'file_id' in before:self.file_cache.pop(before['file_id'],None)
            after=self.fd(pid,item['copy_fd'])
            if source and before and after and 'version' in source and 'version' in after:
                self.event('file_copy',pid,source=source['version'],previous=before['version'],version=after['version'],syscall=nr)
            else:self.event('unresolved_kernel_copy',pid,syscall=nr,bytes=retval)

    def exec(self,pid):
        item=self.pending[pid]
        identity=self.count;self.activities[pid]=identity
        actual=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[0].decode(errors='surrogateescape')
        python=(item['program'] if re.fullmatch(r'python[\d.]*',Path(item['program']).name)
                else actual if re.fullmatch(r'python[\d.]*',Path(actual).name) else None)
        self.event('exec',pid,argv=item['argv'],cwd=item['cwd'],environment=item['environment'],python=python,
                   executable=self.at_path(os.readlink(f'/proc/{pid}/exe')))


def execute(request,store_type):
    if sys.platform!='linux' or platform.machine()!='x86_64':raise RuntimeError('The research observer requires Linux/x86-64')
    started=time.monotonic();recorder=Recorder(request,store_type)
    output=open(request['output'],'wb');child=os.fork()
    if child==0:
        os.setsid();os.chdir(request['workdir']);os.dup2(output.fileno(),1);os.dup2(output.fileno(),2)
        ptrace(TRACEME,0);os.kill(os.getpid(),signal.SIGSTOP)
        os.execve('/bin/sh',['/bin/sh','-c',request['command']],{**os.environ,**request['env']})
    output.close();os.waitpid(child,0);recorder.activities[child]=-1
    ptrace(SETOPTIONS,child,0,OPTIONS);ptrace(SYSCALL,child)
    live={child};detaching=set();timed_out=False;root_code=None;unclaimed={};ready=deque()
    def timeout(signum,frame):
        nonlocal timed_out
        timed_out=True
        for pid in live:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
    previous=signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,request['timeout'])
    try:
        while live:
            pid,status=ready.popleft() if ready else os.waitpid(-1,0x40000000)
            if pid not in recorder.activities:
                # The child's initial stop can be delivered before its parent's
                # FORK/CLONE event. Hold it until that event supplies ancestry.
                unclaimed[pid]=status
                continue
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                live.discard(pid);detaching.discard(pid);code=os.waitstatus_to_exitcode(status)
                recorder.event('exit',pid,returncode=code)
                if pid==child:root_code=code
                if not live:continue
            else:
                stop=os.WSTOPSIG(status);event=status>>16
                try:
                    if pid in detaching and stop==signal.SIGSTOP:
                        recorder.event('unresolved_background_process',pid)
                        ptrace(DETACH,pid,0,signal.SIGCONT);live.remove(pid);detaching.remove(pid)
                        continue
                    if event in {1,2,3}:
                        message=ctypes.c_ulonglong();ptrace(GETEVENTMSG,pid,0,ctypes.addressof(message));new=message.value
                        live.add(new);recorder.activities[new]=recorder.activities[pid]
                        recorder.event('fork',pid,child=new)
                        if new in unclaimed:ready.append((new,unclaimed.pop(new)))
                    elif event==4:
                        message=ctypes.c_ulonglong();ptrace(GETEVENTMSG,pid,0,ctypes.addressof(message));former=message.value
                        if former!=pid:
                            # exec in a non-leader thread takes over the leader
                            # PID; its syscall arguments belong to the old TID.
                            recorder.pending[pid]=recorder.pending.pop(former)
                            recorder.activities[pid]=recorder.activities[former]
                            live.discard(former)
                        recorder.exec(pid)
                    elif stop==(signal.SIGTRAP|128):
                        info=ctypes.create_string_buffer(128);ptrace(GETINFO,pid,128,ctypes.addressof(info))
                        if struct.unpack_from('I',info.raw,4)[0]!=0xc000003e:raise RuntimeError('Unsupported tracee syscall ABI')
                        if info.raw[0]==1:
                            nr,*args=struct.unpack_from('7Q',info.raw,24);recorder.enter(pid,nr,args)
                        elif info.raw[0]==2:recorder.leave(pid,struct.unpack_from('q',info.raw,24)[0])
                    delivery=0 if stop in {signal.SIGTRAP,signal.SIGTRAP|128,signal.SIGSTOP} else stop
                    ptrace(SYSCALL,pid,0,delivery)
                except (ProcessLookupError,FileNotFoundError,PermissionError) as error:
                    if not isinstance(error,ProcessLookupError):
                        if error.filename is None or not error.filename.startswith(f'/proc/{pid}/'):raise
                        if isinstance(error,PermissionError) and not timed_out:raise
                    # SIGKILL/exit_group can invalidate an already queued stop.
                    # Keep the pid live until waitpid supplies its actual exit.
                    recorder.event('termination_pending',pid,reason=str(error))
            if root_code is not None and live and not detaching and not timed_out:
                holds_output=False
                for process in live:
                    try:
                        for fd in Path(f'/proc/{process}/fd').iterdir():
                            try:holds_output|=os.readlink(fd)==request['output']
                            except FileNotFoundError:pass
                    except FileNotFoundError:pass
                if not holds_output:
                    for process in live:
                        try:os.kill(process,signal.SIGSTOP);detaching.add(process)
                        except ProcessLookupError:pass
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous);recorder.log.close()
        for pid in live:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
    size=Path(request['output']).stat().st_size
    return {'returncode':-1 if timed_out else root_code,'timed_out':timed_out,
            'status':'timeout' if timed_out else 'completed','elapsed_seconds':time.monotonic()-started,
            'output_bytes':size,'trace_events':recorder.count}


