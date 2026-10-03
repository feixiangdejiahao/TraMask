"""Archive public documentation explicitly linked by recovered source evidence.

Reference patches, issue discussions and source-code hosting pages are excluded.
This module follows no document links and performs no semantic interpretation.
"""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,urlunsplit
from urllib.request import Request,urlopen


VERSION='explicit-source-linked-document-context.v1'


class DocumentText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.article=[];self.main=[];self.tags=[];self.suppressed=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);self.tags.append(tag)
        if tag in {'script','style','nav','aside','footer'}:self.suppressed+=1
        if tag in {'p','pre','li','h1','h2','h3','h4','tr','section','div'}:self.handle_data('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style','nav','aside','footer'}:self.suppressed=max(0,self.suppressed-1)
        if tag in self.tags:
            index=len(self.tags)-1-self.tags[::-1].index(tag);del self.tags[index:]
        if tag in {'p','pre','li','h1','h2','h3','h4','tr','section','div'}:self.handle_data('\n')
    def handle_data(self,value):
        if self.suppressed:return
        self.parts.append(value)
        if 'article' in self.tags:self.article.append(value)
        if 'main' in self.tags:self.main.append(value)
    def text(self):
        value=''.join(self.article or self.main or self.parts)
        return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',value).strip()


def documentation_url(value):
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or not parsed.hostname or '.' not in parsed.hostname
            or parsed.username or parsed.password or parsed.query):return None
    if any(part in parsed.path.split('/') for part in ('issues','pull','pulls','commit','commits','blob','compare')):
        return None
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))


def fetch(url,directory,*,max_download=2000000,max_text=60000):
    target=documentation_url(url)
    if target is None:return dict(status='excluded_non_documentation_link',url=url)
    key=hashlib.sha256(target.encode()).hexdigest();directory=Path(directory)/key
    if (directory/'manifest.json').exists():return json.loads((directory/'manifest.json').read_text())
    directory.mkdir(parents=True,exist_ok=False)
    result=dict(url=target,requested_source_url=url,retrieved_utc=datetime.now(timezone.utc).isoformat(),
                version=VERSION,followed_document_links=False)
    try:
        request=Request(target,headers={'User-Agent':'SourceContractResearch/1.0'})
        with urlopen(request,timeout=30) as response:
            if documentation_url(response.url) is None:raise ValueError('Redirect leaves document policy')
            raw=response.read(max_download+1);charset=response.headers.get_content_charset() or 'utf-8'
            result.update(final_url=response.url,content_type=response.headers.get_content_type())
        if len(raw)>max_download:raise ValueError('Document download exceeds budget')
        (directory/'response.body').write_bytes(raw)
        decoded=raw.decode(charset)
        if result['content_type']=='text/html':
            parser=DocumentText();parser.feed(decoded);content=parser.text()
        elif result['content_type']=='text/plain':content=decoded
        else:raise ValueError('Unsupported documentation content type')
        (directory/'document.txt').write_text(content)
        result.update(raw_sha256=hashlib.sha256(raw).hexdigest(),text_sha256=hashlib.sha256(content.encode()).hexdigest(),
                      text_path=str((directory/'document.txt').resolve()),text_bytes=len(content.encode()))
        result['status']='complete' if len(content.encode())<=max_text else 'omitted_whole_document_budget'
    except Exception as error:
        result.update(status='unavailable_document',error_type=type(error).__name__,error=str(error))
    (directory/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
