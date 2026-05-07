{{-- Main three-column editor layout --}}
<div
    class="md-doc-editor"
    x-data="mdDocEditor({
        fileType: @js($fileType),
        mergedConfig: @js($mergedConfig),
        resolvedCss: @js($resolvedCss),
    })"
    x-on:content-updated.window="onContentUpdated($event.detail)"
>

    {{-- Pass data to JS on load / Livewire updates --}}
    <script>
        window.mdDocInitialContent  = @js($content);
        window.mdDocConfig          = @js($mergedConfig);
        window.mdDocCss             = @js($resolvedCss);
        window.mdDocFileType        = @js($fileType);
        window.mdDocPath            = @js($path);
        window.mdDocLockKey         = @js($lockKey);
        window.mdDocIsReadOnly      = @js($isReadOnly);
        window.mdDocHeartbeatMs     = @js($lockHeartbeatMs);
    </script>

    <div class="md-doc-layout">

        {{-- LEFT: File tree --}}
        <aside class="md-doc-sidebar">
            <div class="md-doc-sidebar-header">
                <span class="md-doc-sidebar-title">Files</span>
            </div>
            <div class="md-doc-sidebar-body">
                @include('md-doc::components.file-tree', [
                    'nodes'       => $fileTree,
                    'activeLocks' => \MdDoc\FilamentMdDoc\Services\FileLockService::staticActiveLocks(),
                ])
            </div>
        </aside>

        {{-- CENTRE: Monaco editor + included templates bar --}}
        <main class="md-doc-editor-pane">
            <div class="md-doc-editor-toolbar">
                <span class="md-doc-filename">{{ $path ?: 'No file selected' }}</span>

                {{-- Lock status badge --}}
                @if($path)
                    @if($isReadOnly)
                        <span class="md-doc-lock-badge md-doc-lock-readonly">
                            🔒 Read-only · locked by <strong>{{ $lockOwner }}</strong>
                        </span>
                        <button
                            wire:click="tryStealLock"
                            class="md-doc-btn md-doc-btn-sm"
                            title="Try to acquire the lock if it has expired"
                        >Request edit</button>
                    @elseif($lockKey)
                        <span class="md-doc-lock-badge md-doc-lock-mine">
                            ✏️ Editing
                        </span>
                    @endif

                    @if(!$isReadOnly)
                    <button
                        wire:click="save"
                        wire:loading.attr="disabled"
                        class="md-doc-btn md-doc-btn-primary"
                    >
                        <span wire:loading.remove wire:target="save">Save</span>
                        <span wire:loading wire:target="save">Saving…</span>
                    </button>
                    @endif
                @endif
            </div>

            {{-- Monaco container --}}
            <div
                id="md-doc-monaco"
                class="md-doc-monaco-container"
                x-ref="monacoContainer"
            ></div>

            {{-- Included templates --}}
            @if(!empty($includedTemplates))
            <div class="md-doc-includes">
                <span class="md-doc-includes-label">Included templates:</span>
                @foreach($includedTemplates as $tpl)
                    @if($tpl['found'])
                        <button
                            wire:click="openTemplate('{{ $tpl['path'] }}')"
                            class="md-doc-include-btn"
                            title="{{ $tpl['path'] }}"
                        >{{ $tpl['name'] }} ↗</button>
                    @else
                        <span class="md-doc-include-btn md-doc-include-missing" title="Template not found">
                            {{ $tpl['name'] }}
                        </span>
                    @endif
                @endforeach
            </div>
            @endif
        </main>

        {{-- RIGHT: Preview / Config / CSS tabs --}}
        <aside class="md-doc-right-panel">
            <div class="md-doc-tabs" x-data="{ tab: 'preview' }">
                <div class="md-doc-tab-bar">
                    <button
                        class="md-doc-tab"
                        :class="{ 'md-doc-tab-active': tab === 'preview' }"
                        x-on:click="tab = 'preview'"
                    >Preview</button>
                    <button
                        class="md-doc-tab"
                        :class="{ 'md-doc-tab-active': tab === 'config' }"
                        x-on:click="tab = 'config'"
                    >Config</button>
                    <button
                        class="md-doc-tab"
                        :class="{ 'md-doc-tab-active': tab === 'css' }"
                        x-on:click="tab = 'css'"
                    >CSS</button>
                </div>

                {{-- Preview pane --}}
                <div x-show="tab === 'preview'" class="md-doc-panel-body md-doc-preview-body">
                    <div id="md-doc-preview" class="md-doc-preview-content"></div>
                </div>

                {{-- Config pane --}}
                <div x-show="tab === 'config'" class="md-doc-panel-body">
                    @include('md-doc::components.config-panel', [
                        'layers'  => $configLayers,
                        'merged'  => $mergedConfig,
                    ])
                </div>

                {{-- CSS pane --}}
                <div x-show="tab === 'css'" class="md-doc-panel-body">
                    @include('md-doc::components.css-panel', [
                        'css'    => $resolvedCss,
                        'source' => $cssSource,
                    ])
                </div>
            </div>
        </aside>

    </div>{{-- /.md-doc-layout --}}

</div>{{-- /.md-doc-editor --}}

{{-- marked.js --}}
<script src="{{ config('md-doc.marked_url') }}"></script>
{{-- Monaco loader — path controlled by MD_DOC_MONACO_URL in .env --}}
<script>
window.mdDocMonacoBaseUrl = @js(config('md-doc.monaco_base_url'));
</script>
<script src="{{ config('md-doc.monaco_base_url') }}/loader.js"></script>
<script>
require.config({ paths: { vs: window.mdDocMonacoBaseUrl } });
</script>

{{-- Plugin assets --}}
<link rel="stylesheet" href="{{ asset('vendor/md-doc/css/editor.css') }}">
{{-- tokenizers.js must load before editor.js so registerMdDocLanguages() is available --}}
<script src="{{ asset('vendor/md-doc/js/tokenizers.js') }}"></script>
<script src="{{ asset('vendor/md-doc/js/editor.js') }}" defer></script>
