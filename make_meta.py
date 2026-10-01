import json
import subprocess
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any, List

@dataclass
class SectionMetadata:
    section_id: str
    candidate_id: int
    video_id: str
    file_name: str
    file_path: str
    start_offset: float
    end_offset: float
    target_duration_s: float
    probed_duration_s: float
    original_candidate_ranges: list[dict[str, float]]
    padded_range: dict[str, float]
    streams: list[dict[str, Any]] = field(default_factory=list)
    combined_text: str = ''
    reason: str = ''
    def to_dict(self) -> dict[str, Any]: return asdict(self)

def probe_media_duration(f: Path) -> float:
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(f)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return round(float(res.stdout.strip()), 3) if res.stdout.strip() else 0.0

def probe_media_info(f: Path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,duration', '-of', 'json', str(f)]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)

video_id = 'S-7VkwSU0gs'
base = Path('/root/youtubr_clipper/media/downloads') / video_id
padded = json.loads((base / 'padded_ranges.json').read_text())
sections_dir = base / 'sections'
url = f'https://www.youtube.com/watch?v={video_id}'

extracted = []
sec = 1
for ci, cand in enumerate(padded['candidates'], 1):
    for pr in cand.get('padded_ranges', cand.get('ranges', [])):
        s = f'section_{sec:03d}'
        mp4 = sections_dir / f'{s}.mp4'
        dur = round(pr['end'] - pr['start'], 2)
        pdur = probe_media_duration(mp4)
        pi = probe_media_info(mp4)
        meta = SectionMetadata(
            section_id=s, candidate_id=ci, video_id=video_id,
            file_name=mp4.name, file_path=str(mp4),
            start_offset=pr['start'], end_offset=pr['end'],
            target_duration_s=dur, probed_duration_s=pdur,
            original_candidate_ranges=cand.get('original_ranges', cand.get('ranges', [])),
            padded_range=pr,
            streams=[{'index':x.get('index'),'codec_name':x.get('codec_name'),'codec_type':x.get('codec_type'),'duration':x.get('duration')} for x in pi.get('streams',[])],
            combined_text=cand.get('combined_text',''), reason=cand.get('reason','')
        )
        (sections_dir / f'{s}.json').write_text(json.dumps(meta.to_dict(), indent=2))
        print(f'Wrote {s}.json')
        extracted.append(meta.to_dict())
        sec += 1

(sections_dir / 'sections_metadata.json').write_text(json.dumps({'video_id':video_id,'video_url':url,'total_sections':len(extracted),'sections':extracted}, indent=2))
print('Manifest written')