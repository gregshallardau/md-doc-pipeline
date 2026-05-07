{{-- Recursive file tree component --}}
{{-- $nodes: array of ['name', 'path', 'type', 'children'?] --}}
{{-- $activeLocks: optional map of path → locked_by --}}
{{-- $dirtyPaths: optional map of path → true for files with uncommitted changes --}}
@php
    $activeLocks ??= [];
    $dirtyPaths  ??= [];
@endphp

<ul class="md-doc-tree">
    @foreach($nodes as $node)
        <li class="md-doc-tree-item md-doc-tree-{{ $node['type'] }}">

            @if($node['type'] === 'dir')
                <details class="md-doc-tree-dir" open>
                    <summary class="md-doc-tree-dir-label">
                        <span class="md-doc-tree-icon">📁</span>
                        {{ $node['name'] }}
                    </summary>
                    @if(!empty($node['children']))
                        @include('md-doc::components.file-tree', ['nodes' => $node['children']])
                    @endif
                </details>

            @elseif($node['type'] === 'md')
                @php
                    $isLocked = isset($activeLocks[$node['path']]);
                    // dirtyPaths is keyed by repo-relative path; node path is workspace-relative
                    // so we check both forms for safety.
                    $isDirty  = isset($dirtyPaths[$node['path']])
                             || collect($dirtyPaths)->keys()->contains(fn($p) => str_ends_with($p, $node['path']));
                @endphp
                <button
                    wire:click="loadFile('{{ $node['path'] }}')"
                    class="md-doc-tree-file md-doc-tree-file-md {{ $isLocked ? 'md-doc-tree-file-locked' : '' }} {{ $isDirty ? 'md-doc-tree-file-dirty' : '' }}"
                    title="{{ $isLocked ? 'Locked by ' . $activeLocks[$node['path']] : ($isDirty ? 'Uncommitted changes · ' . $node['path'] : $node['path']) }}"
                >
                    <span class="md-doc-tree-icon">{{ $isLocked ? '🔒' : '📄' }}</span>
                    {{ $node['name'] }}
                    @if($isDirty)
                        <span class="md-doc-tree-dirty-dot" aria-label="modified">●</span>
                    @endif
                </button>

            @elseif($node['type'] === 'meta')
                <button
                    wire:click="loadFile('{{ $node['path'] }}')"
                    class="md-doc-tree-file md-doc-tree-file-meta"
                    title="{{ $node['path'] }}"
                >
                    <span class="md-doc-tree-icon">⚙️</span>
                    {{ $node['name'] }}
                </button>

            @elseif($node['type'] === 'css')
                <button
                    wire:click="loadFile('{{ $node['path'] }}')"
                    class="md-doc-tree-file md-doc-tree-file-css"
                    title="{{ $node['path'] }}"
                >
                    <span class="md-doc-tree-icon">🎨</span>
                    {{ $node['name'] }}
                </button>
            @endif

        </li>
    @endforeach
</ul>
