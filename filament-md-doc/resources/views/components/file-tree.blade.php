{{-- Recursive file tree component --}}
{{-- $nodes: array of ['name', 'path', 'type', 'children'?] --}}

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
                <button
                    wire:click="loadFile('{{ $node['path'] }}')"
                    class="md-doc-tree-file md-doc-tree-file-md"
                    title="{{ $node['path'] }}"
                >
                    <span class="md-doc-tree-icon">📄</span>
                    {{ $node['name'] }}
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
