# Harness: cho AI làm lại nội dung mà không sai số

Harness là bộ "luật + máy kiểm tra" của dự án. AI agent (Claude Code hay agent khác) đọc nó để
hiểu dự án, sửa đúng chỗ, và tự kiểm tra trước khi báo xong.

## Gồm những gì

| File | Để làm gì |
|---|---|
| `AGENTS.md` | Hướng dẫn cho AI: dự án là gì, file nào làm gì, số liệu lấy từ đâu, luật viết nội dung, thế nào là "xong" |
| `CLAUDE.md` | Claude Code tự đọc file này khi mở dự án (nó gọi lại `AGENTS.md`) |
| `harness/facts.toml` | Danh sách các con số chính đang viết trong README, mỗi số kèm công thức lấy từ `results/` |
| `harness/check.py` | Máy kiểm tra: tính lại từng số, so với chữ trong file, báo chỗ sai |
| `inputs/` + `inputs/INDEX.md` | Chỗ bỏ tài liệu mới; bảng ghi tài liệu nào dùng cho phần nào |
| `.claude/commands/refresh.md` | Lệnh `/refresh` trong Claude Code: đọc tài liệu mới, làm lại nội dung, kiểm tra |
| `.claude/commands/audit.md` | Lệnh `/audit`: chỉ soát lỗi, không sửa gì |
| `config/apis.md` | Bảng API: thêm dòng khi dự án cần dịch vụ ngoài |
| `.env.example` → `.env` | Chỗ để key API thật (`.env` không bao giờ lên GitHub) |

## Khi có tài liệu mới

1. Chép file vào `inputs/` (tài liệu không được chia sẻ thì để trong `inputs/private/`, không lên GitHub).
2. Thêm 1 dòng vào `inputs/INDEX.md`, cột Status ghi `new`.
3. Mở dự án trong Claude Code, gõ `/refresh`. Agent sẽ đọc tài liệu, nói trước sẽ đổi gì,
   chờ bạn đồng ý nếu phải đổi phần mô phỏng, rồi chạy lại, sửa chữ cả tiếng Anh lẫn tiếng Việt,
   và chạy máy kiểm tra.
4. Muốn chỉ soát lỗi thì gõ `/audit`.

`/refresh` chạy bằng gói Claude Code của bạn, không cần API key.

## Máy kiểm tra báo gì

```bash
.venv\Scripts\python harness\check.py --tests
```

- **facts**: số trong README có khớp kết quả mới nhất không. Ví dụ chạy lại ra 97.5% mà README vẫn ghi 97.7% → FAIL, chỉ rõ file và số đúng.
- **forbidden**: có câu nói quá không (ví dụ nói đã triển khai ở công ty điện, hay đã kiểm chứng bằng dữ liệu thật) hay chữ về tính năng đã bỏ. Danh sách nằm cuối `harness/facts.toml`.
- **fresh**: bản copy trên trang web (`docs/data`, Monitor, phân tích lỗi) có cũ hơn kết quả không.
- **links**: link trong các file `.md` có trỏ tới file có thật không.
- **secrets**: có key API nào lỡ bị đưa vào git không.
- **apis**: bảng API, `.env.example` và code có khớp nhau không.

Cuối cùng phải ra `0 failed`. `WARN` là lưu ý, không chặn.

## Thêm API khi mở rộng

1. Thêm 1 dòng vào bảng trong `config/apis.md` (Name, Env var, Status, Purpose, Used by, Cost, Docs).
   Status: `planned` = chưa dùng, `active` = code đang dùng, `off` = khóa lại.
2. Thêm tên biến vào `.env.example` (để trống), key thật vào `.env`.
3. Trong code: `from shf import apis` rồi `apis.key("Tên")`. Dòng chưa `active` sẽ bị chặn, nên không lỡ gọi API tốn tiền.
4. Xem key nào đã có: `.venv\Scripts\python -m shf.apis` (không bao giờ in key ra).

Hiện bảng có 2 dòng `planned`: Claude API (viết lại nội dung tự động hàng loạt) và EIA (số liệu SAIDI/SAIFI thật để so sánh).
