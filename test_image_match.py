"""
이미지 매칭 테스트 스크립트
갱신 버튼을 찾을 수 있는지 테스트
"""
from pathlib import Path
import unittest

def test_image_matching():
    """이미지 매칭 테스트"""
    try:
        import cv2
        from src.image_matcher import read_image, matching_failure_guidance
    except ModuleNotFoundError as exc:
        raise unittest.SkipTest("OpenCV가 설치되지 않아 이미지 매칭 테스트를 건너뜁니다.") from exc

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
    screenshot = read_image(str(screenshot_path))
    template = read_image(str(refresh_button_path))
    
    if screenshot is None:
        print(f"❌ 스크린샷을 로드할 수 없습니다: {screenshot_path}")
        return
    
    if template is None:
        print(f"❌ 템플릿을 로드할 수 없습니다: {refresh_button_path}")
        return
    
    print(f"✅ 스크린샷 크기: {screenshot.shape}")
    print(f"✅ 템플릿 크기: {template.shape}")
    if template.shape[0] > screenshot.shape[0] or template.shape[1] > screenshot.shape[1]:
        print("❌ 템플릿이 스크린샷보다 큽니다. 해상도와 템플릿 크기를 확인하세요.")
        return
    
    # 다양한 임계값으로 테스트
    thresholds = [0.99, 0.95, 0.92, 0.90, 0.85, 0.80, 0.75, 0.70]
    
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    for threshold in thresholds:
        
        if max_val >= threshold:
            print(f"✅ 임계값 {int(threshold*100)}%: 매칭 성공! (신뢰도: {max_val:.4f}, 위치: {max_loc})")
        else:
            print(f"❌ 임계값 {int(threshold*100)}%: 매칭 실패 (최대 신뢰도: {max_val:.4f})")
    
    print("\n" + "="*60)
    print(f"최대 매칭 신뢰도: {max_val:.4f} ({int(max_val*100)}%)")
    if max_val < 0.95:
        print(matching_failure_guidance(max_val))
    print("="*60)

if __name__ == "__main__":
    test_image_matching()
