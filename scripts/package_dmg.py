"""Build the macOS disk image from the same allowlisted payload as the Beta ZIP."""
import hashlib
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.version import VERSION


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('请在 macOS 上构建 DMG。')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise SystemExit('请先运行 npm --prefix frontend run build。')

    out = ROOT / 'release'
    name = f'shiye-{VERSION}-mac-arm64'
    archive = out / f'{name}.zip'
    image = out / f'{name}.dmg'
    subprocess.run([sys.executable, str(ROOT / 'scripts/package_beta.py')], check=True)

    with tempfile.TemporaryDirectory(prefix='.shiye-dmg-', dir=out) as temporary:
        staging = Path(temporary) / 'staging'
        staging.mkdir()
        # ditto preserves the executable bit on the Finder launcher.
        subprocess.run(['ditto', '-x', '-k', str(archive), str(staging)], check=True)
        (staging / 'Applications').symlink_to('/Applications')
        candidate = Path(temporary) / image.name
        subprocess.run([
            'hdiutil', 'create', '-quiet', '-fs', 'HFS+', '-format', 'UDZO',
            '-volname', f'拾页 {VERSION}', '-srcfolder', str(staging), str(candidate),
        ], check=True)
        subprocess.run(['hdiutil', 'verify', '-quiet', str(candidate)], check=True)
        candidate.replace(image)

    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    image.with_suffix('.dmg.sha256').write_text(f'{digest}  {image.name}\n')
    print(image)


if __name__ == '__main__':
    main()
