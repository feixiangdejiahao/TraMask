cat > aiomonitor/webui/templates/snapshots.html <<'EOF'
{% extends "layout.html" %}
{% block head_content %}
<div class="py-2">
  <form class="flex items-end gap-x-2"
        hx-post="/api/snapshot/"
        hx-swap="none"
        hx-on::after-request="if(event.detail.successful){ htmx.trigger(document.getElementById('snapshot-list-body'), 'refresh', {}); }">
    <div>
      <label for="snapshot-name" class="block text-sm font-medium leading-6 text-gray-900">Name (optional)</label>
      <input type="text" id="snapshot-name" name="name" placeholder="snapshot name"
             class="inline-flex w-60 rounded-md border-0 py-1 pl-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6" />
    </div>
    <button type="submit"
            class="rounded bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
      Save snapshot
    </button>
  </form>
</div>
<div class="py-2 flex items-end gap-x-2">
  <div>
    <label for="diff-snapshot-1" class="block text-sm font-medium leading-6 text-gray-900">Diff snapshot 1</label>
    <input type="text" id="diff-snapshot-1" name="snapshot_id_1" placeholder="snapshot id"
           class="inline-flex w-40 rounded-md border-0 py-1 pl-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6" />
  </div>
  <div>
    <label for="diff-snapshot-2" class="block text-sm font-medium leading-6 text-gray-900">Diff snapshot 2</label>
    <input type="text" id="diff-snapshot-2" name="snapshot_id_2" placeholder="snapshot id"
           class="inline-flex w-40 rounded-md border-0 py-1 pl-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6" />
  </div>
  <button type="button"
          class="rounded bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          hx-post="/api/snapshot/diff"
          hx-include="#diff-snapshot-1, #diff-snapshot-2"
          hx-target="#snapshot-diff"
          hx-swap="innerHTML"
          mustache-template="snapshot-diff-template">
    Diff
  </button>
</div>
{% endblock %}
{% block content %}
<div class="px-4 sm:px-6 lg:px-8">
  <div class="mt-4 flow-root">
    <div class="-mx-4 -my-2 overflow-x-auto sm:-mx-6 lg:-mx-8">
      <div class="inline-block min-w-full px-0 py-2 align-middle">
        <table class="min-w-full divide-y divide-gray-300">
          <thead>
            <tr>
              <th scope="col" class="py-2.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 sm:pl-0">ID</th>
              <th scope="col" class="px-1 py-2.5 text-left text-sm font-semibold text-gray-900">Name</th>
              <th scope="col" class="px-1 py-2.5 text-left text-sm font-semibold text-gray-900">Running</th>
              <th scope="col" class="px-1 py-2.5 text-left text-sm font-semibold text-gray-900">Terminated</th>
              <th scope="col" class="relative py-3.5 pl-3 pr-4 sm:pr-0">
                <span class="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody id="snapshot-list-body" class="divide-y divide-gray-200"
                 hx-trigger="load,every 2s,refresh from:body"
                 hx-get="/api/snapshot/"
                 hx-swap="innerHTML"
                 mustache-template="snapshot-list">
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div id="snapshot-diff" class="mt-6"></div>

{% raw %}
<template id="snapshot-list">
{{# snapshots}}
<tr>
  <td class="whitespace-nowrap px-1 py-2 text-sm font-medium text-gray-900">{{ id }}</td>
  <td class="whitespace-nowrap px-1 py-2 text-sm text-gray-500">{{ name }}</td>
  <td class="whitespace-nowrap px-1 py-2 text-sm text-gray-500">{{ running_count }}</td>
  <td class="whitespace-nowrap px-1 py-2 text-sm text-gray-500">{{ terminated_count }}</td>
  <td class="relative whitespace-nowrap px-1 py-2 text-right text-sm font-medium sm:pr-0">
    <a class="cursor-pointer rounded bg-indigo-600 px-2 py-1 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500"
       hx-post="/api/snapshot/tasks"
       hx-vals='{"snapshot_id": "{{ id }}"}'
       hx-target="#snapshot-diff"
       hx-swap="innerHTML"
       mustache-template="snapshot-tasks-template">Show</a>
    <button type="button"
            class="rounded bg-rose-600 px-2 py-1 text-xs font-semibold text-white shadow-sm hover:bg-rose-500"
            hx-delete="/api/snapshot"
            hx-vals='{"snapshot_id": "{{ id }}"}'
            hx-swap="none"
            hx-on::after-request="if(event.detail.successful){ htmx.trigger(document.getElementById('snapshot-list-body'), 'refresh', {}); }">Delete</button>
  </td>
</tr>
{{/ snapshots}}
</template>

<template id="snapshot-tasks-template">
<h2 class="font-mono text-sm py-1 px-2 my-2 rounded shadow-sm border-2 border-slate-400 bg-gray-50">Running tasks</h2>
<table class="min-w-full divide-y divide-gray-300">
  <thead>
    <tr>
      <th class="text-left text-sm font-semibold text-gray-900 px-2">Task ID</th>
      <th class="text-left text-sm font-semibold text-gray-900 px-2">State</th>
      <th class="text-left text-sm font-semibold text-gray-900 px-2">Name</th>
      <th class="text-left text-sm font-semibold text-gray-900 px-2">Coroutine</th>
      <th class="text-left text-sm font-semibold text-gray-900 px-2">Since</th>
    </tr>
  </thead>
  <tbody>
{{# tasks}}
    <tr>
      <td class="whitespace-nowrap px-2 py-2 text-sm text-gray-900 font-mono">{{ task_id }}</td>
      <td class="whitespace-nowrap px-2 py-2 text-sm text-gray-500">{{ state }}</td>
      <td class="whitespace-nowrap px-2 py-2 text-sm text-gray-500">{{ name }}</td>
      <td class="whitespace-nowrap px-2 py-2 font-mono text-xs text-gray-500">{{ coro }}</td>
      <td class="whitespace-nowrap px-2 py-2 font-mono text-sm text-gray-500">{{ since }}</td>
    </tr>
{{/ tasks}}
  </tbody>
</table>
</template>

<template id="snapshot-diff-template">
<h2 class="font-mono text-sm py-1 px-2 my-2 rounded shadow-sm border-2 border-slate-400 bg-gray-50">Added ({{ added.length }})</h2>
<ul>
{{# added}}
  <li class="px-2 py-1 text-sm font-mono">{{ task_id }} {{ kind }} {{ name }} {{ coro }}</li>
{{/ added}}
</ul>
<h2 class="font-mono text-sm py-1 px-2 my-2 rounded shadow-sm border-2 border-slate-400 bg-gray-50">Removed ({{ removed.length }})</h2>
<ul>
{{# removed}}
  <li class="px-2 py-1 text-sm font-mono">{{ task_id }} {{ kind }} {{ name }} {{ coro }}</li>
{{/ removed}}
</ul>
<h2 class="font-mono text-sm py-1 px-2 my-2 rounded shadow-sm border-2 border-slate-400 bg-gray-50">Common ({{ common.length }})</h2>
<ul>
{{# common}}
  <li class="px-2 py-1 text-sm font-mono">{{ task_id }} {{ kind }} {{ name }} {{ coro }}</li>
{{/ common}}
</ul>
</template>
{% endraw %}
{% endblock %}
EOF
echo "template created"