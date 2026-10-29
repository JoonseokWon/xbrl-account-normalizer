"""Create a portable Qt desktop EXE; business-data validation is not run."""
import os
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DEPS=ROOT/'.build-tools'
if DEPS.exists():sys.path.insert(0,str(DEPS))
from version import VERSION

def make_icon(path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtCore import Qt
    from PySide6.QtSvg import QSvgRenderer
    app=QApplication.instance() or QApplication([])
    image=QImage(256,256,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);renderer=QSvgRenderer(str(ROOT/'assets/app-icon.svg'));renderer.render(painter);painter.end()
    png=path.with_suffix('.png');image.save(str(png))
    from PIL import Image
    Image.open(png).save(path,format='ICO',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])

def main():
    import PyInstaller.__main__
    target=ROOT/'dist'/VERSION
    work=ROOT/'build'/VERSION
    specs=work/'specs'
    for folder in (target,work,specs):
        if not folder.resolve().is_relative_to(ROOT):raise ValueError('프로젝트 밖 빌드 경로')
    if (target/'AccountDataNormalizer').exists():raise FileExistsError('기존 EXE 묶음을 덮어쓰지 않습니다.')
    specs.mkdir(parents=True,exist_ok=True)
    icon=work/'app.ico';make_icon(icon)
    os.environ['PYINSTALLER_CONFIG_DIR']=str(ROOT/'.build-cache/pyinstaller')
    excluded=['numpy','pandas','matplotlib','scipy','IPython','PyQt5','PyQt6','PySide2','tkinter']
    spec=f'''from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata,collect_data_files,collect_submodules
root=Path({str(ROOT)!r})
data=[(str(root/name),name) for name in ('config','assets','samples','vendor')]
for package in ('PySide6-Essentials','shiboken6','openpyxl','lxml','arelle-release'):
    data+=copy_metadata(package)
data+=collect_data_files('arelle',includes=['config/**','resources/**','locale/**','images/**','*.md'])
hidden=['PySide6.QtSvg']+collect_submodules('arelle',filter=lambda name:not any(name.startswith(prefix) for prefix in ('arelle.plugin','arelle.conformance','arelle.webserver')))
a=Analysis([str(root/'main.py')],pathex={[str(ROOT),str(DEPS)]!r},
           binaries=[],datas=data,hiddenimports=hidden,
           hookspath=[],hooksconfig={{}},runtime_hooks=[],excludes={excluded!r},noarchive=False)
# Qt uses the Windows ICU API. Do not shadow it with another Python package's
# incompatible, identically named ICU DLL.
a.binaries=[entry for entry in a.binaries if not
            (Path(entry[0]).name.lower().startswith('icu') and Path(entry[0]).suffix.lower()=='.dll')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='AccountDataNormalizer',
        debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
        console=False,disable_windowed_traceback=False,icon={[str(icon)]!r})
collect=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='AccountDataNormalizer')
'''
    spec_path=specs/'AccountDataNormalizer.spec';spec_path.write_text(spec,encoding='utf-8')
    PyInstaller.__main__.run([str(spec_path),'--clean','--distpath',str(target),'--workpath',str(work/'analysis-isolated')])
    portable=target/'AccountDataNormalizer'
    for name in ('README.md','SECURITY.md','docs/MANUAL_VALIDATION.md','docs/RELEASE_NOTES.md','docs/THIRD_PARTY_NOTICES.md'):
        destination=portable/Path(name).name
        shutil.copy2(ROOT/name,destination)
    (portable/'docs').mkdir(exist_ok=True)
    for path in (ROOT/'docs').iterdir():
        if path.is_file() and path.suffix in ('.md','.txt'):shutil.copy2(path,portable/'docs'/path.name)
    licenses=portable/'licenses';licenses.mkdir(exist_ok=True)
    for name in ('PySide6-Essentials','shiboken6','openpyxl','et_xmlfile','Pillow','PyInstaller','lxml','arelle-release','attrs','bottle','certifi','filelock','isodate','jaconv','jsonschema','jsonschema-specifications','pyparsing','python-dateutil','referencing','regex','rpds-py','six','truststore','typing-extensions'):
        package=distribution(name)
        for item in package.files or []:
            lower=str(item).lower()
            if any(word in lower for word in ('license','licence','copying','authors')):
                source=Path(package.locate_file(item))
                if source.is_file():
                    destination=licenses/name/Path(str(item)).name
                    destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    for source in (ROOT/'assets/licenses').glob('*.txt'):
        shutil.copy2(source,licenses/source.name)
    shutil.copy2(ROOT/'assets/fonts/OFL.txt',licenses/'NotoSansKR-OFL.txt')
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copy2(python_license,licenses/'Python-LICENSE.txt')
    (portable/'시작하기.txt').write_text('AccountDataNormalizer.exe를 실행해 주세요.\nPython 설치 없이 사용할 수 있어요.\n_internal 폴더는 EXE와 함께 보관해 주세요.\n테스트 원장 변환·감사 입력의 확인 범위는 README.md와 RELEASE_NOTES.md에서 볼 수 있어요.\n',encoding='utf-8')
    print('Portable EXE created: '+str(portable))

if __name__=='__main__':main()
