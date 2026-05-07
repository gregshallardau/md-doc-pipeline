{{-- CSS theme viewer panel --}}
{{-- $css:    resolved CSS content string --}}
{{-- $source: relative path to the source file --}}

<div class="md-doc-css-panel">

    @if(empty($css))
        <p class="md-doc-config-empty">No CSS theme found for this document.</p>
    @else
        @if($source)
        <div class="md-doc-css-source-bar">
            <span class="md-doc-css-source-label">Source:</span>
            <code class="md-doc-css-source-path">{{ $source }}</code>
            <button
                wire:click="loadFile('{{ $source }}')"
                class="md-doc-btn md-doc-btn-sm"
                title="Open this file in the editor"
            >Edit ↗</button>
        </div>
        @endif

        <pre class="md-doc-css-content"><code>{{ $css }}</code></pre>
    @endif

</div>
