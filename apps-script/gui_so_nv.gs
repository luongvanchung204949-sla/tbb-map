/**
 * Gửi số NV giao theo bưu cục từ file "AI - Data nguồn" (sheet "12. Nhân sự")
 * sang web TBB Map — chạy bằng tài khoản email GHN, mỗi ngày sau 10h.
 *
 * Cách cài (một lần):
 *   1. Mở https://script.google.com bằng email GHN → Dự án mới → dán toàn bộ đoạn này.
 *   2. Chọn hàm `guiSoNV` → bấm Chạy → cho phép quyền (đọc Google Sheets, kết nối dịch vụ bên ngoài).
 *      Xem "Nhật ký thực thi": phải thấy "OK: 54 BC, tổng ... NV".
 *   3. Chọn hàm `caiLich` → bấm Chạy một lần để đặt lịch tự động hằng ngày.
 */
const CFG = {
  SHEET_ID: '1XY-mNcQvaQqF5kk7EzwFWGNDIWu0TiZIwi0uJQeaBBA',
  SHEET_NAME: '12. Nhân sự',
  CHUC_VU: 'Business Development Field Executive',
  TRANG_THAI: 'Đang làm việc',
  URL: 'https://tbb-map-production.up.railway.app/api/nv',
  KEY: 'DAN_NV_KEY_VAO_DAY'  // lấy từ biến NV_KEY trên Railway,
};

function guiSoNV() {
  const sh = SpreadsheetApp.openById(CFG.SHEET_ID).getSheetByName(CFG.SHEET_NAME);
  if (!sh) throw new Error('Không tìm thấy sheet ' + CFG.SHEET_NAME);
  const v = sh.getDataRange().getDisplayValues();
  const h = v[0].map(function (x) { return String(x).trim(); });
  const iC = h.indexOf('Chức vụ'), iF = h.indexOf('Trạng thái'), iG = h.indexOf('Bưu cục');
  if (iC < 0 || iF < 0 || iG < 0) throw new Error('Thiếu cột Chức vụ / Trạng thái / Bưu cục ở dòng 1');

  const dem = {};
  for (let r = 1; r < v.length; r++) {
    if (String(v[r][iC]).trim() !== CFG.CHUC_VU) continue;
    if (String(v[r][iF]).trim() !== CFG.TRANG_THAI) continue;
    const bc = String(v[r][iG]).split(' - ')[0].trim();   // "22945000 - (SLA) Chiềng Sinh" -> "22945000"
    if (!bc) continue;
    dem[bc] = (dem[bc] || 0) + 1;
  }
  const rows = Object.keys(dem).map(function (k) { return { bc: k, nv: dem[k] }; });
  if (!rows.length) throw new Error('Không đếm được NV nào — kiểm tra lại tên chức vụ/trạng thái');

  const res = UrlFetchApp.fetch(CFG.URL, {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-Nv-Key': CFG.KEY },
    payload: JSON.stringify({ rows: rows, source: 'File nhân sự GHN · ' + CFG.SHEET_NAME }),
    muteHttpExceptions: true,
  });
  const code = res.getResponseCode(), body = res.getContentText();
  if (code !== 200) throw new Error('Web trả lỗi ' + code + ': ' + body);
  const j = JSON.parse(body);
  Logger.log('OK: ' + j.ok + ' BC, tổng ' + j.total_nv + ' NV' + (j.unmatched.length ? ' · không khớp: ' + j.unmatched.join(', ') : ''));
}

/** Đặt lịch: 10h30 (sau khi file cập nhật lúc 10h) và 13h00 (chạy lại phòng khi file cập nhật muộn). */
function caiLich() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'guiSoNV') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('guiSoNV').timeBased().atHour(10).nearMinute(30).everyDays(1).inTimezone('Asia/Ho_Chi_Minh').create();
  ScriptApp.newTrigger('guiSoNV').timeBased().atHour(13).nearMinute(0).everyDays(1).inTimezone('Asia/Ho_Chi_Minh').create();
  Logger.log('Đã đặt lịch chạy 10h30 và 13h00 hằng ngày.');
}
