"""Build the macOS disk image from the same allowlisted payload as the Beta ZIP."""
import hashlib
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.version import VERSION


def build_app(staging: Path, archive: Path, name: str):
    sources = ROOT / 'scripts/macos'
    app = staging / '拾页.app'
    contents = app / 'Contents'
    resources = contents / 'Resources'
    executable = contents / 'MacOS' / 'AINotes'
    executable.parent.mkdir(parents=True)
    resources.mkdir()

    subprocess.run(['ditto', '-x', '-k', str(archive), str(resources)], check=True)
    (resources / name).rename(resources / 'project')
    launcher = resources / '启动拾页.command'
    launcher.write_text((sources / 'launch.command').read_text().replace('@VERSION@', VERSION))
    launcher.chmod(0o755)

    with tempfile.TemporaryDirectory(prefix='shiye-icon-') as temp:
        iconset = Path(temp) / 'AINotes.iconset'
        iconset.mkdir()
        master = Path(temp) / 'master.png'
        subprocess.run(['xcrun', 'swift', str(sources / 'Icon.swift'), str(master)], check=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                suffix = '@2x' if scale == 2 else ''
                subprocess.run([
                    'sips', '-z', str(pixels), str(pixels), str(master),
                    '--out', str(iconset / f'icon_{size}x{size}{suffix}.png'),
                ], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['iconutil', '-c', 'icns', str(iconset),
                        '-o', str(resources / 'AINotes.icns')], check=True)
        shutil.copyfile(master, archive.parent / f'{name}-icon.png')

    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'io.github.zhuxinleibandou.AINotes',
        'CFBundleName': '拾页',
        'CFBundleDisplayName': '拾页',
        'CFBundleExecutable': executable.name,
        'CFBundlePackageType': 'APPL',
        'CFBundleIconFile': 'AINotes.icns',
        'CFBundleShortVersionString': VERSION.split('-')[0],
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '14.0',
        'LSUIElement': True,
    }))
    subprocess.run(['xcrun', 'swiftc', '-O', '-target', 'arm64-apple-macos14.0',
                    str(sources / 'Launcher.swift'), '-o', str(executable)], check=True)
    subprocess.run(['xattr', '-cr', str(app)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True)


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

    with tempfile.TemporaryDirectory(prefix='shiye-dmg-') as temporary:
        staging = Path(temporary) / 'staging'
        staging.mkdir()
        build_app(staging, archive, name)
        shutil.copyfile(ROOT / 'BETA.md', staging / '安装说明.md')
        (staging / 'Applications').symlink_to('/Applications')
        candidate = Path(temporary) / image.name
        subprocess.run([
            'hdiutil', 'create', '-quiet', '-fs', 'HFS+', '-format', 'UDZO',
            '-volname', f'拾页 {VERSION}', '-srcfolder', str(staging), str(candidate),
        ], check=True)
        subprocess.run(['hdiutil', 'verify', '-quiet', str(candidate)], check=True)
        shutil.move(candidate, image)

    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    image.with_suffix('.dmg.sha256').write_text(f'{digest}  {image.name}\n')
    print(image)


if __name__ == '__main__':
    main()
