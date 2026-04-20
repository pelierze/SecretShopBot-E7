"""
PNG 이미지 파일의 sBIT 메타데이터 문제를 수정하는 스크립트
libpng warning을 근본적으로 해결합니다.
"""
import os
from pathlib import Path
from PIL import Image

def fix_png_file(png_path):
    """PNG 파일을 다시 저장하여 메타데이터 문제 수정"""
    try:
        # 이미지 열기
        img = Image.open(png_path)
        
        # 백업 생성 (원본 파일명 유지)
        backup_path = Path(str(png_path).rsplit('.', 1)[0] + '_backup.png')
        if not backup_path.exists():
            import shutil
            shutil.copy(png_path, backup_path)
            print(f"  백업 생성: {backup_path}")
        
        # 이미지를 RGB 또는 RGBA로 변환 후 저장 (메타데이터 제거)
        if img.mode in ('RGBA', 'LA', 'PA'):
            # 알파 채널이 있는 경우
            img_fixed = img.convert('RGBA')
        else:
            # 알파 채널이 없는 경우
            img_fixed = img.convert('RGB')
        
        # 최적화하여 다시 저장 (메타데이터 제거됨)
        img_fixed.save(png_path, optimize=True)
        print(f"✅ 수정 완료: {png_path}")
        
    except Exception as e:
        print(f"❌ 오류 발생 ({png_path}): {e}")

def main():
    """모든 PNG 파일 수정"""
    project_root = Path(__file__).parent
    
    # images 폴더의 모든 PNG 파일 찾기
    png_files = list(project_root.glob("images/**/*.png"))
    
    print(f"총 {len(png_files)}개의 PNG 파일을 수정합니다...\n")
    
    for png_file in png_files:
        print(f"처리 중: {png_file}")
        fix_png_file(png_file)
        print()
    
    print("="*60)
    print("✅ 모든 PNG 파일 수정 완료!")
    print("="*60)
    print("\n백업 파일(*_backup.png)은 images 폴더에 저장되었습니다.")
    print("문제가 없으면 백업 파일을 삭제하셔도 됩니다.")

if __name__ == "__main__":
    main()
