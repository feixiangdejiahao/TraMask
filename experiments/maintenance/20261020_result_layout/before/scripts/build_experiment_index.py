"""Build a local experiment catalog without changing historical artifacts."""
from collections import Counter
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    catalog = json.loads((ROOT / 'experiments/catalog.json').read_text())
    counts = Counter(row['group'] for row in catalog['entries'])
    sections = []
    for group, title in catalog['groups'].items():
        rows = []
        for entry in catalog['entries']:
            if entry['group'] != group:
                continue
            # Open historical documents through their original URL. This preserves
            # relative links and avoids editing frozen experimental evidence.
            old = html.escape(entry['old'], quote=True)
            new = html.escape(entry['new'], quote=True)
            name = html.escape(Path(entry['old']).name)
            kind = '研究记录' if entry['old'].startswith('research/') else '运行结果'
            storage = ('文档已归档；旧路径保留链接' if entry['mode'] == 'archived_document_with_original_path_link'
                       else '冻结材料保留原位置；此处为分组链接')
            rows.append(f'<tr><td>{kind}</td><td><a href="../{old}">{name}</a>'
                        f'<br><small>{new}<br>{storage}</small></td><td>{entry["files"]:,}</td></tr>')
        sections.append(f'<details open><summary>{html.escape(title)} '
                        f'<span>({counts[group]})</span></summary><table>'
                        '<thead><tr><th>类型</th><th>材料及存放位置</th><th>文件数</th></tr></thead>'
                        f'<tbody>{"".join(rows)}</tbody></table></details>')
    page = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>实验材料索引</title><style>
body{font:16px/1.65 system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 22px;color:#243047;background:#fafbfc}
h1{margin-bottom:8px}a{color:#125fb5}p{max-width:950px}input{font:inherit;box-sizing:border-box;width:100%;padding:12px;border:1px solid #bbc6d4;border-radius:6px;margin:18px 0}
details{background:white;border:1px solid #dce2ea;border-radius:8px;padding:14px 18px;margin:14px 0}summary{cursor:pointer;font-weight:650}summary span,small{color:#65758a}small{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;margin-top:12px}th,td{text-align:left;border-bottom:1px solid #e9edf2;padding:9px;vertical-align:top}th:first-child{width:85px}th:last-child{width:80px}tr[hidden],details[hidden]{display:none}code{background:#edf1f6;padding:2px 5px;border-radius:3px}
</style></head><body><h1>实验材料索引</h1>
<p>历史实验按主题归拢入口。每个主题使用 <code>research/</code> 组织记录，使用 <code>results/</code> 组织运行产物。新算法代码从仓库的 <code>src/</code> 开始，新算法测试放在 <code>tests/augmentation/</code>。</p>
<p>120 份历史方案文档已归档，旧路径保留兼容链接。冻结结果、JSON 记录和目录树保留原物理位置，通过主题链接集中访问。这使严格比较绝对路径的历史凭据继续有效。下方链接沿用原路径，保留历史文档的相对链接。实验内容和原有代码没有改写。</p>
<p><a href="../README.md">仓库说明</a> · <a href="../docs/README.md">研究报告</a> · <a href="catalog.json">机器可读目录</a> · <a href="maintenance/20261007/migration.json">迁移及清理清单</a> · <a href="maintenance/20261007/verification.json">整理后检查</a></p>
<label for="filter">按实验名、文件名或目录筛选</label><input id="filter" type="search" placeholder="例如：automatic_augmentation、20261005、census">
''' + '\n'.join(sections) + '''
<script>
document.querySelector('#filter').addEventListener('input', event => {
  const term = event.target.value.trim().toLowerCase();
  document.querySelectorAll('details').forEach(section => {
    let visible = 0;
    section.querySelectorAll('tbody tr').forEach(row => {
      row.hidden = !row.textContent.toLowerCase().includes(term);
      if (!row.hidden) visible += 1;
    });
    section.hidden = visible === 0;
    if (term) section.open = true;
  });
});
</script></body></html>'''
    target = ROOT / 'experiments/index.html'
    target.write_text(page)
    return {'path': str(target.relative_to(ROOT)), 'entries': len(catalog['entries']), 'groups': len(sections)}


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False))
