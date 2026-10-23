"""Separate cancellable process keeps model memory out of the web server."""
import json
import sys
from pathlib import Path
import mlx_whisper

result = mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo=sys.argv[2], word_timestamps=True,
    hallucination_silence_threshold=2.0, verbose=False, condition_on_previous_text=False)
segments = [dict(start=s['start'], end=s['end'], text=s['text'].strip()) for s in result['segments']
            if s['text'].strip() and s.get('no_speech_prob',0) < .8]
target = Path(sys.argv[3])
staged = target.with_suffix('.json.tmp')
staged.write_text(json.dumps(segments, ensure_ascii=False))
staged.replace(target)
