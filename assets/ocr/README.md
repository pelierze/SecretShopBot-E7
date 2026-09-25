# Korean OCR model

`korean_PP-OCRv4_rec_mobile.onnx` is the Korean PP-OCRv4 recognition model distributed by RapidAI/RapidOCR (PaddleOCR model family).

- Source: https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/rec/korean_PP-OCRv4_rec_mobile.onnx
- Model catalog: https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml
- License: Apache-2.0; see `LICENSE-RapidOCR.txt`.
- Size: 24,067,780 bytes.
- SHA-256: `ab151ba9065eccd98f884cf4d927db091be86137276392072edd4f9d43ad7426`

Bundled by the PyInstaller spec. Runtime does not download models or send images online. Loaded lazily only for unknown-event text mode; the existing digit recognizer is unchanged. RapidOCR detection and recognition use two CPU threads each.
