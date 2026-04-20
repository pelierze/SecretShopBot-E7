"""
이미지 매칭 테스트 스크립트
갱신 버튼을 찾을 수 있는지 테스트
"""
import cv2
import numpy as np
from pathlib import Path

def test_image_matching():
    """이미지 매칭 테스트"""
    base_dir = Path(__file__).parent
    
    # 스크린샷 경로 (봇이 마지막으로 저장한 스크린샷)
    screenshot_path = base_dir / "screenshot.png"
    
    # 갱신 버튼 이미지
    refresh_button_path = base_dir / "images" / "buttons" / "refresh_button.png"
    
    if not screenshot_path.exists():
        print(f"❌ 스크린샷이 없습니다: {screenshot_path}")
        print("먼저 봇을 한 번 실행해주세요.")
        return
    
    if not refresh_button_path.exists():
        print(f"❌ 갱신 버튼 이미지가 없습니다: {refresh_button_path}")
        return
    
    # 이미지 로드
    screenshot = cv2.imread(str(screenshot_path))
    template = cv2.imread(str(refresh_button_path))
    
    if screenshot is None:
        print(f"❌ 스크린샷을 로드할 수 없습니다: {screenshot_path}")
        return
    
    if template is None:
        print(f"❌ 템플릿을 로드할 수 없습니다: {refresh_button_path}")
        return
    
    print(f"✅ 스크린샷 크기: {screenshot.shape}")
    print(f"✅ 템플릿 크기: {template.shape}")
    
    # 다양한 임계값으로 테스트
    thresholds = [0.99, 0.95, 0.92, 0.90, 0.85, 0.80, 0.75, 0.70]
    
    for threshold in thresholds:
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= threshold:
            print(f"✅ 임계값 {int(threshold*100)}%: 매칭 성공! (신뢰도: {max_val:.4f}, 위치: {max_loc})")
        else:
            print(f"❌ 임계값 {int(threshold*100)}%: 매칭 실패 (최대 신뢰도: {max_val:.4f})")
    
    print("\n" + "="*60)
    print(f"최대 매칭 신뢰도: {max_val:.4f} ({int(max_val*100)}%)")
    print(f"권장 임계값: {int(max_val*0.95*100)}% (최대값의 95%)")
    print("="*60)

if __name__ == "__main__":
    test_image_matching()
