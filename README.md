# TBB Map — Địa giới, vol tồn & định mức bưu cục (GHN Tây Bắc Bộ)

Web bản đồ 54 BC / 754 xã cũ / 257 xã mới vùng TBB: tô màu mức tải, đánh dấu tuyến thiếu người, định mức theo BC và theo xã.

## Chạy
- Railway: `uvicorn app.main:app` (xem `railway.json`). Gắn **volume** vào `/data` và đặt biến `DATA_DIR=/data`.
- Biến môi trường:
  - `EDIT_PIN` — mã PIN để sửa định mức/tuyến (để trống = ai cũng sửa được).
  - `ADMIN_PIN` — mã PIN quản trị: tải báo cáo tồn đọng mới, tải file sao lưu.
- Local: `pip install -r requirements.txt && DATA_DIR=./data uvicorn app.main:app --reload`

## Cấu trúc
- `app/main.py` — API (FastAPI) + SQLite (`/data/app.db`): định mức chung/BC/xã, tuyến thiếu người, nhật ký.
- `app/vol.py` — xử lý file *Báo cáo tồn đọng lấy/giao/trả* → `/data/vol.json` (ghép xã theo tên + huyện, quy đổi tên đặc biệt).
- `app/ref/master.json` — gán 754 xã cũ → BC (từ file "TBB - Link Lisa"), huyện cũ, xã mới.
- `app/static/data/*.json` — ranh giới: lãnh thổ BC, xã mới (vietnamese-provinces-database, MIT), xã cũ (GADM 4.1, cắt theo xã mới), BC, tỉnh.
- `app/static/index.html` — giao diện (MapLibre).

## Cập nhật thường gặp
- **Vol hằng ngày:** tab *Cập nhật dữ liệu* → chọn file tồn đọng → PIN quản trị.
- **Định mức / tuyến:** sửa trực tiếp trên web (PIN sửa).
- **Gán xã ↔ BC thay đổi:** cập nhật `app/ref/master.json` và lớp `lanh_tho_bc.json` (cần chạy lại script dựng ranh giới).
- **Sao lưu:** tab *Cập nhật dữ liệu* → Tải file sao lưu (Excel).
