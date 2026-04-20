"""
이미지 매칭을 위한 모듈
OpenCV를 사용하여 화면에서 이미지 찾기
"""
import cv2
import numpy as np
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)


class ImageMatcher:
    """화면에서 이미지를 찾는 클래스"""
    
    def __init__(self, threshold: float = 0.8):
        """
        Args:
            threshold: 이미지 매칭 임계값 (0.0 ~ 1.0)
        """
        self.threshold = threshold
        
    def find_image(self, screen_img_path: str, template_img_path: str, 
                   threshold: Optional[float] = None) -> Optional[Tuple[int, int, int, int]]:
        """
        화면에서 템플릿 이미지 찾기
        
        Args:
            screen_img_path: 스크린샷 이미지 경로
            template_img_path: 찾을 템플릿 이미지 경로
            threshold: 매칭 임계값 (지정하지 않으면 기본값 사용)
            
        Returns:
            이미지를 찾은 경우 (x, y, width, height), 못 찾은 경우 None
        """
        try:
            # 이미지 로드
            screen = cv2.imread(screen_img_path, cv2.IMREAD_COLOR)
            template = cv2.imread(template_img_path, cv2.IMREAD_COLOR)
            
            if screen is None:
                logger.error(f"스크린샷 이미지를 불러올 수 없음: {screen_img_path}")
                return None
            
            if template is None:
                logger.error(f"템플릿 이미지를 불러올 수 없음: {template_img_path}")
                return None
            
            # 템플릿 매칭
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            # 임계값 확인
            threshold_value = threshold if threshold is not None else self.threshold
            
            if max_val >= threshold_value:
                # 템플릿 크기
                h, w = template.shape[:2]
                x, y = max_loc
                
                logger.debug(f"이미지 발견: {template_img_path} at ({x}, {y}) - 유사도: {max_val:.2f}")
                return (x, y, w, h)
            else:
                logger.debug(f"이미지 미발견: {template_img_path} - 최대 유사도: {max_val:.2f}")
                return None
                
        except Exception as e:
            logger.error(f"이미지 매칭 중 오류: {e}")
            return None
    
    def find_all_images(self, screen_img_path: str, template_img_path: str,
                       threshold: Optional[float] = None) -> List[Tuple[int, int, int, int]]:
        """
        화면에서 템플릿 이미지의 모든 위치 찾기
        
        Args:
            screen_img_path: 스크린샷 이미지 경로
            template_img_path: 찾을 템플릿 이미지 경로
            threshold: 매칭 임계값
            
        Returns:
            찾은 모든 위치의 리스트 [(x, y, width, height), ...]
        """
        try:
            # 이미지 로드
            screen = cv2.imread(screen_img_path, cv2.IMREAD_COLOR)
            template = cv2.imread(template_img_path, cv2.IMREAD_COLOR)
            
            if screen is None or template is None:
                logger.error("이미지를 불러올 수 없음")
                return []
            
            # 템플릿 매칭
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            
            # 임계값 확인
            threshold_value = threshold if threshold is not None else self.threshold
            
            # 임계값 이상의 모든 위치 찾기
            locations = np.where(result >= threshold_value)
            
            # 템플릿 크기
            h, w = template.shape[:2]
            
            # 결과 리스트
            matches = []
            for pt in zip(*locations[::-1]):  # x, y 순서로 변환
                matches.append((pt[0], pt[1], w, h))
            
            # 중복 제거 (비최대 억제)
            matches = self._non_max_suppression(matches, 0.3)
            
            logger.debug(f"이미지 발견 개수: {len(matches)}")
            return matches
            
        except Exception as e:
            logger.error(f"이미지 매칭 중 오류: {e}")
            return []
    
    def get_similarity(self, screen_img_path: str, template_img_path: str) -> float:
        """
        화면과 템플릿 이미지의 유사도 계산
        
        Args:
            screen_img_path: 스크린샷 이미지 경로
            template_img_path: 비교할 템플릿 이미지 경로
            
        Returns:
            유사도 (0.0 ~ 1.0), 오류 시 0.0
        """
        try:
            # 이미지 로드
            screen = cv2.imread(screen_img_path, cv2.IMREAD_COLOR)
            template = cv2.imread(template_img_path, cv2.IMREAD_COLOR)
            
            if screen is None or template is None:
                return 0.0
            
            # 템플릿 매칭
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            return float(max_val)
            
        except Exception as e:
            logger.error(f"유사도 계산 중 오류: {e}")
            return 0.0
    
    def get_similarity_at_location(self, screen_img_path: str, template_img_path: str, 
                                    location: Tuple[int, int, int, int]) -> float:
        """
        특정 위치에서 화면과 템플릿 이미지의 유사도 계산
        
        Args:
            screen_img_path: 스크린샷 이미지 경로
            template_img_path: 비교할 템플릿 이미지 경로
            location: 비교할 위치 (x, y, w, h)
            
        Returns:
            유사도 (0.0 ~ 1.0), 오류 시 0.0
        """
        try:
            # 이미지 로드
            screen = cv2.imread(screen_img_path, cv2.IMREAD_COLOR)
            template = cv2.imread(template_img_path, cv2.IMREAD_COLOR)
            
            if screen is None or template is None:
                return 0.0
            
            x, y, w, h = location
            
            # 화면에서 해당 영역 추출
            screen_region = screen[y:y+h, x:x+w]
            
            # 템플릿과 비교
            if screen_region.shape != template.shape:
                # 크기가 다르면 템플릿 매칭 사용
                result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                return float(max_val)
            else:
                # 크기가 같으면 직접 비교
                result = cv2.matchTemplate(screen_region, template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                return float(max_val)
            
        except Exception as e:
            logger.error(f"위치별 유사도 계산 중 오류: {e}")
            return 0.0
    
    def _non_max_suppression(self, boxes: List[Tuple[int, int, int, int]], 
                            overlap_thresh: float = 0.3) -> List[Tuple[int, int, int, int]]:
        """
        비최대 억제를 통해 겹치는 박스 제거
        
        Args:
            boxes: 박스 리스트 [(x, y, w, h), ...]
            overlap_thresh: 겹침 임계값
            
        Returns:
            필터링된 박스 리스트
        """
        if len(boxes) == 0:
            return []
        
        # 박스를 numpy 배열로 변환
        boxes_array = np.array(boxes)
        
        # 좌표 추출
        x1 = boxes_array[:, 0]
        y1 = boxes_array[:, 1]
        x2 = boxes_array[:, 0] + boxes_array[:, 2]
        y2 = boxes_array[:, 1] + boxes_array[:, 3]
        
        # 면적 계산
        areas = boxes_array[:, 2] * boxes_array[:, 3]
        
        # 정렬 (y 좌표 기준)
        idxs = np.argsort(y1)
        
        pick = []
        
        while len(idxs) > 0:
            last = len(idxs) - 1
            i = idxs[last]
            pick.append(i)
            
            # 겹치는 박스 찾기
            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])
            
            w = np.maximum(0, xx2 - xx1)
            h = np.maximum(0, yy2 - yy1)
            
            overlap = (w * h) / areas[idxs[:last]]
            
            # 겹침이 임계값 이하인 박스만 유지
            idxs = np.delete(idxs, np.concatenate(([last], 
                             np.where(overlap > overlap_thresh)[0])))
        
        return [boxes[i] for i in pick]
    
    def get_center(self, box: Tuple[int, int, int, int]) -> Tuple[int, int]:
        """
        박스의 중심 좌표 계산
        
        Args:
            box: (x, y, width, height)
            
        Returns:
            (center_x, center_y)
        """
        x, y, w, h = box
        return (x + w // 2, y + h // 2)
