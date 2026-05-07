{{-- Git history panel --}}
{{-- $history: list of {sha, short, author, date, subject} --}}
{{-- $currentBranch: current git branch name (or null) --}}
{{-- $isDirty: bool — whether the current file has uncommitted changes --}}

<div class="md-doc-history-panel">

    @if($currentBranch)
    <div class="md-doc-history-branch">
        Branch: <code>{{ $currentBranch }}</code>
        @if($isDirty)
            <span class="md-doc-history-dirty" title="Uncommitted changes">●&nbsp;modified</span>
        @endif
    </div>
    @endif

    @if(empty($history))
        <p class="md-doc-config-empty">No git history for this file.</p>
    @else
        <ul class="md-doc-history-list">
            @foreach($history as $commit)
            <li class="md-doc-history-item">
                <button
                    x-on:click="$dispatch('show-diff', { sha: '{{ $commit['sha'] }}', short: '{{ $commit['short'] }}' })"
                    class="md-doc-history-button"
                    title="Compare working copy to {{ $commit['short'] }}"
                >
                    <span class="md-doc-history-sha"><code>{{ $commit['short'] }}</code></span>
                    <span class="md-doc-history-subject">{{ $commit['subject'] }}</span>
                    <span class="md-doc-history-meta">{{ $commit['author'] }} · {{ $commit['date'] }}</span>
                </button>
            </li>
            @endforeach
        </ul>
    @endif

</div>
