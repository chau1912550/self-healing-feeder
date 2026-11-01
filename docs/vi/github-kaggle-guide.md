# Hướng dẫn: đẩy code lên GitHub → chạy trên Kaggle → tải kết quả về

Tổng thời gian khoảng 30 phút cho lần đầu. Sau khi làm xong, bạn có thể xóa thư mục `.venv` trên máy để lấy lại khoảng 500 MB.

---

## Phần 1. Đẩy code lên GitHub

### Bước 1. Tạo repo trên GitHub (làm trên trình duyệt)
1. Đăng nhập [github.com](https://github.com), bấm **New** (hoặc **+ → New repository**).
2. **Repository name:** `self-healing-feeder`.
3. Chọn **Public**. Kaggle chỉ tải trực tiếp được repo công khai, và nhà tuyển dụng cũng cần xem được repo.
4. **Không** tick "Add a README", "Add .gitignore" hay "License", vì dự án đã có sẵn các file này.
5. Bấm **Create repository**. Giữ trang đó mở để lấy đường link `https://github.com/<tên-bạn>/self-healing-feeder.git`.

### Bước 2. Đẩy code từ máy lên (mở terminal)

> **Quan trọng:** chỉ chạy `git init` **bên trong thư mục `self-healing-feeder`**, đừng chạy ở thư mục `01_ca_nhan`. Thư mục `01_ca_nhan` có hộ chiếu, I-94 và hồ sơ cá nhân; mình đã kiểm tra thư mục đó hiện không phải repo git.

Lần đầu dùng git trên máy này, khai báo tên và email để ghi vào commit. Nên dùng email mà bạn đã đăng ký với GitHub:

```bash
git config --global user.name "Ten Cua Ban"
```

```bash
git config --global user.email "email-github-cua-ban@example.com"
```

Sau đó chạy lần lượt các lệnh sau:

```bash
cd "D:/Download form Google/01_ca_nhan/self-healing-feeder"
```

```bash
git init
```

```bash
git add .
```

Trước khi commit, kiểm tra danh sách file sắp đẩy lên:

```bash
git status
```

Danh sách **phải có:** `shf/`, `scripts/`, `data/feeder/`, `tests/`, `notebooks/`, `docs/`, `scada/`, `run.py`, `README.md` và các file nhỏ trong `results/` (ảnh, `metrics.json`…).

Danh sách **không được có:** `.venv/`, `data/generated/` (dataset), `models/` (model.pkl). File `.gitignore` đã loại sẵn các file này.

```bash
git commit -m "Self-healing feeder: ML fault location and automated restoration on IEEE 123-bus"
```

```bash
git branch -M main
```

```bash
git remote add origin https://github.com/<ten-ban>/self-healing-feeder.git
```

```bash
git push -u origin main
```

Lần đầu `git push`, Windows sẽ mở cửa sổ đăng nhập GitHub (Git Credential Manager). Bạn đăng nhập trên trình duyệt là xong. **Không** dán mật khẩu hay token vào code hoặc vào chat.

Tải lại trang repo trên GitHub: phần README sẽ hiện kèm các biểu đồ.

### Lần sau khi sửa code

```bash
git add . && git commit -m "Mo ta thay doi" && git push
```

---

## Phần 2. Chạy trên Kaggle

> **Chưa muốn đẩy lên GitHub?** Bỏ qua Phần 1 và làm theo mục **"Cách dễ nhất"** ở cuối phần này. Cách đó dùng file zip đóng gói sẵn, không cần Internet hay xác minh số điện thoại.

### Bước 1. Chuẩn bị tài khoản (chỉ làm một lần)
1. Đăng ký tại [kaggle.com](https://www.kaggle.com).
2. Vào **Settings → Phone verification**, xác minh số điện thoại. Nếu không xác minh, notebook không được bật Internet, nên không tải được code từ GitHub và không cài được OpenDSS.

### Bước 2. Mở notebook
1. Trên Kaggle: **Create → New Notebook**.
2. Menu **File → Import Notebook** → chọn file `notebooks/kaggle_run.ipynb` trên máy bạn.
   - Cách khác: chọn tab **GitHub** trong hộp Import rồi dán link repo, rồi chọn `notebooks/kaggle_run.ipynb`.
3. Ở khung bên phải, mục **Settings**:
   - **Internet → On**.
   - **Accelerator → None.** Dự án chỉ dùng CPU; bật GPU không nhanh hơn mà còn tốn hạn mức GPU hàng tuần.

### Bước 3. Sửa một dòng rồi chạy
Ở ô thứ hai, thay `<your-username>` bằng tên GitHub của bạn:

```python
REPO_URL = "https://github.com/<ten-ban>/self-healing-feeder.git"
```

Có 2 cách chạy:
- **Run All:** chạy ngay trong phiên đang mở, nhưng phải để tab trình duyệt mở đến khi xong.
- **Save Version → Save & Run All (Commit):** Kaggle chạy ở chế độ nền. Bạn đóng trình duyệt được, quay lại sau xem kết quả. **Nên dùng cách này.**

Bản đầy đủ (11.448 sự cố) dự kiến mất khoảng 10–20 phút với khoảng 4 nhân CPU của Kaggle. Muốn chạy thử nhanh trước thì đặt `QUICK = True`.

### Cách dễ nhất: không cần GitHub, không cần Internet, không cần xác minh số điện thoại
Mình đã đóng gói sẵn file **`dist/self-healing-feeder-kaggle.zip`** (22 MB). File gồm code và bộ cài OpenDSS dành cho Linux, nên notebook cài được offline.

1. Trên Kaggle: **Create → New Notebook → File → Import Notebook**, chọn `notebooks/kaggle_run.ipynb`.
2. Ở khung bên phải: **Add Input → Upload** (hoặc **+ Add Data → Upload**). Kéo file `dist/self-healing-feeder-kaggle.zip` vào, đặt tên dataset (ví dụ `self-healing-feeder`), để ở chế độ **Private**, rồi bấm **Create**. Kaggle sẽ tự giải nén.
3. **Settings → Accelerator → None.** Internet để tắt cũng được.
4. Để nguyên `REPO_URL` như mặc định. Bấm **Save Version → Save & Run All**.

Notebook tự tìm thư mục có `run.py` trong `/kaggle/input`, rồi cài OpenDSS từ thư mục `wheels/` có sẵn trong file zip.

---

## Phần 3. Tải kết quả về

Notebook sẽ nén thư mục `results/` thành **`results.zip`** (khoảng 17 MB). Có 3 cách tải:
- **Đang chạy trực tiếp:** bấm link `results.zip` ở cuối notebook, hoặc mở mục **Output** ở khung bên phải → `/kaggle/working/results.zip` → **⋮ → Download**.
- **Đã chạy bằng Save Version:** mở trang notebook → tab **Output** → tải `results.zip`.
- **Dòng lệnh (không bắt buộc):** cài `pip install kaggle`, tạo API token ở **Settings → API → Create New Token** rồi lưu file `kaggle.json` vào `C:\Users\<bạn>\.kaggle\`, sau đó chạy:

```bash
kaggle kernels output <ten-kaggle>/<ten-notebook> -p results_kaggle
```

Token này giống như mật khẩu: không đưa lên GitHub, không dán vào notebook hay vào chat.

**Bên trong `results.zip` có:** `metrics.json` (mọi con số), các biểu đồ PNG, `restoration.csv`, `switching_orders.md`, `zones.csv`, `model.pkl` và `dataset.csv.gz`.

---

## Phần 4. Giải phóng dung lượng trên máy (sau khi Kaggle chạy được)

| Muốn xóa | Lấy lại | Cách tạo lại khi cần |
|---|---|---|
| Thư mục `self-healing-feeder/.venv` | ~508 MB (ổ D:) | `python -m venv .venv` rồi `.venv\Scripts\python -m pip install -r requirements.txt` |
| `data/generated/dataset.csv.gz` | 16 MB | chạy lại `run.py` |
| Bộ nhớ đệm pip: `python -m pip cache purge` | ~1,3 GB (ổ C:) | pip tự tải lại khi cài thư viện |

Code và kết quả chính vẫn nằm trên GitHub, nên xóa các thứ trên không làm mất dự án.

---

## Lưu ý
- Notebook đã được **chạy thử trên môi trường giả lập** trên máy này: lấy code, cài OpenDSS, kiểm tra nhanh lưới, hiện kết quả, nén zip đều chạy đúng. Nhưng **chưa chạy trên Kaggle thật**. Kaggle có thể dùng phiên bản Python, pandas hoặc scikit-learn khác. Nếu gặp lỗi, chép thông báo lỗi gửi mình để sửa.
- Các hạn mức của Kaggle (số nhân CPU, thời gian một phiên, giờ GPU) có thể thay đổi. Xem con số hiện tại trong tài khoản Kaggle của bạn.
