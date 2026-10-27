# Video Trung → Việt trên Mac

Mở `start-dub.command`, sau đó truy cập http://127.0.0.1:7860.
Giao diện studio riêng (FastAPI + HTML/CSS/JavaScript), không còn dùng Gradio. Tải video lên, tùy chọn mẫu giọng rõ tiếng 3–10 giây và đúng transcript, bấm **Tạo video tiếng Việt**.
Nhận diện, tách nền và tạo giọng chạy local. Bước dịch dùng agy CLI đã đăng nhập, gửi toàn bộ phụ đề Trung và ảnh ghép 12 frame đến model được chọn trong agy; cần Internet cho bước dịch. Không cần nhập API key vào ứng dụng.

Có thể bổ sung thuật ngữ Trung–Việt vào `local_dub/glossary.json`; bộ dịch chỉ dùng các mục xuất hiện trong nội dung video.

Không có mẫu: OmniVoice tạo giọng Việt đầu tiên rồi dùng chính giọng đó cho các câu sau.

Luồng chạy: FFmpeg tách âm thanh → Demucs tách vocals/bass/drums/other → OCR phụ đề Trung trên video (Qwen3-ASR trên âm thanh gốc khi không có phụ đề đủ tin cậy) → agy dịch toàn bộ phụ đề cùng ảnh ghép 12 frame (4×3) → lưu bản dịch dài → Whisper căn lời Trung đã nhận diện vào âm thanh gốc → agy chia nguyên văn bản dịch vào các mốc câu ngắn → OmniVoice MPS → FFmpeg atempo căn từng đoạn → ducking theo âm lượng thực tế của lời Việt (attack 15 ms, release 250 ms) → trộn nền không có vocals Trung → xuất MP4/AAC, WAV và SRT.

Đầu ra trong `data/local_dub/<mã video và cấu hình>/`:

- `video_tieng_viet.mp4`: video thành phẩm, giữ luồng hình gốc.
- `mixed_vi.wav`: âm thanh thành phẩm.
- `voice_vi.wav`: chỉ giọng Việt sau căn thời gian.
- `background.wav`: nền đã bỏ stem vocals.
- `translated_blocks.json`: bản dịch dài đã chốt với toàn bộ bối cảnh, trước bước chia câu.
- `source_word_alignment.json`, `sentence_anchors.json`: mốc từ/câu Trung được căn theo âm thanh gốc.
- `partition_audit.json`: kiểm tra bước chia câu; nối các mảnh phải giữ nguyên mọi từ của bản dịch dài theo thứ tự.
- `segments.json`: lời Trung, bản dịch Việt theo câu ngắn và timestamp.
- `vietnamese.srt`: phụ đề Việt rời (chưa burn vào hình).
- `status.json`, `process.log`: tiến độ và log.

Giới hạn bản đầu: tối đa 5 phút, một giọng Việt xuyên suốt; không lip-sync và không xóa chữ Trung có sẵn trên hình. Bản dịch và nhận diện tự động vẫn có thể sai tên riêng, từ chuyên môn hoặc lời bị nhiễu. Demucs có thể còn sót giọng hoặc làm mất một phần hiệu ứng. Ưu tiên giữ đủ nghĩa; cho phép tăng tốc tối đa 3× và chỉ viết gọn lại khi giọng thực tế quá dài.

Mỗi lần bấm **Thêm vào hàng đợi** hoặc **Chạy lại** ở video đã xong đều tạo một lượt mới, kể cả video cũ: dịch và tạo giọng lại, có thể dùng lại bước tách nền/nhận diện. Mở nhiều tab chỉ theo dõi cùng hàng đợi, không tự tạo tác vụ. Chỉ chống lặp lại đúng một request tải lên khi mạng gửi lại request đó.

Hàng đợi và lịch sử lưu tại `data/studio.sqlite3`. Chỉ một worker chạy tại một thời điểm, có khóa tiến trình để mở thêm cửa sổ server không tạo thêm worker. Có tạm dừng nhận việc tiếp theo, tiếp tục, hủy và chạy lại. Tạm dừng hàng đợi vẫn cho video đang chạy hoàn tất. Đóng tab không dừng tác vụ; mở lại sẽ đọc trạng thái chung. Nếu tắt app giữa chừng, tác vụ chưa xong được khôi phục và dùng lại các bước hoàn tất. Kết quả từng lượt được giữ riêng tại `data/studio_results/<job-id>/`, không bị lượt sau ghi đè.

## Dùng trên điện thoại

Giao diện tự co về một cột, nút và hàng đợi phù hợp thao tác chạm. Thanh tải lên hiển thị phần trăm thực tế trước khi tác vụ vào hàng đợi; sau khi chọn video có thể **Đổi video** hoặc **Bỏ** để chọn lại.

Studio là PWA: trên Android dùng nút **Cài app** hoặc menu trình duyệt; trên iPhone/iPad mở bằng Safari, chọn **Chia sẻ → Thêm vào Màn hình chính**. Bấm **Bật thông báo** để nhận báo khi video hoàn tất hoặc lỗi trong lúc app đang hoạt động. Để điện thoại mở app qua mạng LAN, server cần được truy cập từ điện thoại bằng một địa chỉ an toàn mà trình duyệt cho phép service worker/thông báo; `127.0.0.1` trên điện thoại trỏ về chính điện thoại, không phải Mac.

Trong mục **Dùng giọng của riêng bạn**, có thể chọn một **Giọng đã lưu**. Để thêm giọng mới: chọn mẫu âm thanh 3–10 giây, nhập đúng lời nói, tick **Lưu mẫu này để dùng lần sau** và đặt tên. File mẫu cùng transcript được giữ local trong `data/studio_voices/`; một video dùng giọng đã lưu sẽ trỏ đến đúng mẫu đó thay vì tải lại nó trong mỗi job.

Toàn bộ câu và timestamp được gửi một lượt đến agy, ưu tiên giữ đủ ý thay vì tóm tắt mạnh. Sau khi dịch xong mới chia lời Việt theo các câu Trung đã được căn vào âm thanh gốc bằng forced alignment từ Whisper large-v3 có sẵn. Bước này không nhận diện/dịch lại lời Trung, không chia mốc thời gian theo tỷ lệ số chữ. Bước chia phải giữ nguyên toàn bộ từ tiếng Việt trong từng đoạn và đúng thứ tự; chỉ được đổi dấu câu. Giọng Việt chỉ bắt đầu tại mốc câu tương ứng; khoảng nghỉ giữa các câu được giữ lại. Giới hạn độ dài cho phép tăng tốc đến 3×; khoảng 2× là mục tiêu tham khảo. Sau OmniVoice, hệ thống đo thời lượng thật: chỉ câu cần vượt 3× mới được agy viết gọn và tạo giọng lại tối đa hai vòng, hướng tới khoảng 2×. Không xuất giọng vượt 3× hoặc cắt bỏ lời cuối. Nếu vẫn không khớp, tác vụ báo lỗi rõ câu cần chỉnh.

Model nhận diện và giọng tải một lần; bước dịch qua agy cần kết nối tới nhà cung cấp model và phiên đăng nhập hợp lệ.

## CLI

```sh
cd /Users/macbook/Project/langswap
.venv/bin/python -m local_dub /absolute/path/video.mp4 --duck-db 9 --steps 16
```

## Môi trường

App dùng `.venv` của Langswap, có thêm `mlx-audio` cho Qwen3-ASR và agy CLI cho dịch: `.[api]` với torch/torchaudio 2.8.0 và faster-whisper. OmniVoice chạy bằng `../OmniVoice/.venv/bin/python` (cần transformers, torch và OmniVoice). Hai môi trường tách rời để tránh xung đột.

- `OMNIVOICE_ROOT`: đổi đường dẫn thư mục OmniVoice.
- `DUB_AGY_MODEL`: model dịch trong `agy models`; mặc định `gemini-3.8-flash-medium`.
- `DUB_AGY_BIN`: đường dẫn agy CLI nếu không có trong PATH.
- Lỗi CLI gốc được lưu ở `agy_raw.json`, `agy_stderr.log`; schema tránh enum số do backend Gemini không hỗ trợ. ID được kiểm tra đầy đủ tại máy.
- `DUB_ALIGNMENT_MODEL`: model faster-whisper đã cache tại `models_weights`; mặc định `large-v3`, dùng CPU int8 để căn lời Trung vào âm thanh.
- `DUB_OMNIVOICE_MODEL`: model ID hoặc đường dẫn weights khác.
- `DUB_FFMPEG`, `DUB_FFPROBE`: đổi executable FFmpeg/ffprobe. Mặc định dùng bản đang hoạt động trong `../voice-text-studio/resources/ffmpeg/darwin-arm64/` nếu có.

## Kiểm thử

OCR xử lý luồng JPEG theo lô 24 frame, chỉ giữ một lô ảnh tạm trên ổ đĩa. Mỗi lô nhận diện hoàn tất được lưu JSON trong `screen_text/ocr_batches_v3/`: khi tiếp tục sau lỗi, hệ thống giải mã lại video nhưng dùng lại các lô OCR đã xong. Lượt khác cùng video có thể dùng lại kết quả nhận diện gốc; kiểm tra video thành phẩm vẫn quét riêng ở 30 frame/giây. Khi bật xử lý chữ, âm thanh được trộn trước rồi ghép cùng bản hình cuối, bỏ MP4 trung gian.

Vùng OCR nhiễu và phụ đề khớp lời thoại được lọc trên máy. Những vùng còn lại được gửi agy theo lô tối đa 80, mỗi lô có toàn bộ lời thoại làm ngữ cảnh và cache riêng; các vùng vượt 80 được chia sang lô tiếp theo, không bỏ bản dịch.

Khi kiểm thử thực tế, dùng clip khoảng 10–15 giây theo yêu cầu người dùng; không chạy lại toàn bộ video dài nếu chưa được yêu cầu.

```sh
.venv/bin/python -m unittest discover -s tests -p test_local_dub.py -v
```

## Nhịp đọc đồng đều

Sau dịch toàn bộ và chia câu, `pacing.py` chọn một nhịp chung theo phân vị 75% có trọng số âm tiết, trong khoảng 4.8–7 âm tiết/giây. Câu quá dày không được đẩy tốc độ chung lên vô hạn: nó được gửi lại agy kèm ngân sách từ và toàn bộ ngữ cảnh, tối đa hai vòng, ưu tiên giữ hành động, đối tượng và số liệu. Bản chia gốc trước điều chỉnh giữ tại `partitioned_segments.json`.

Mỗi câu có thời lượng đích theo số âm tiết và nhịp chung; độ linh hoạt tối đa 12% với các câu thông thường. Không dời thời điểm bắt đầu sớm. Cho phép dùng thêm tối đa 250 ms khoảng nghỉ cuối câu, giữ 80 ms trước câu tiếp theo nếu có khoảng trống. OmniVoice nhận `duration` ngay khi sinh giọng; FFmpeg căn thời lượng còn lệch thay vì để mỗi câu tự chọn một nhịp riêng. `pacing_plan.json` và các trường `target_duration`, `expected_sps`, `fitted_speech_seconds` trong kết quả hỗ trợ kiểm tra. Giới hạn xử lý 3× vẫn được giữ.

## Chữ Trung trên hình (thử nghiệm)

Thiết lập **Chữ Trung trên hình** có ba lựa chọn: **Giữ nguyên hình**, **Chỉ che phụ đề Trung**, hoặc **Việt hóa chữ theo kiểu gốc**. Mặc định tắt; giao diện nhớ lựa chọn cho lần sau. Chế độ Việt hóa che phụ đề và thay các nhãn bằng chữ Việt nền trong suốt, màu/viền gần kiểu gốc và bố cục ổn định. Nút **Xử lý chữ** trên video đã hoàn tất tạo tác vụ riêng dùng lại nguyên âm thanh Việt và phụ đề đã lưu; chọn chế độ ở mục **Chữ Trung trên hình** rồi bấm nút này. Khi đang chọn giữ nguyên hình, nút hướng dẫn chọn chế độ trước, không tự bật Việt hóa. Không cần chạy lại ASR, dịch lời thoại hay OmniVoice.

Apple Vision quét toàn màn hình 30 lần/giây, theo dõi vùng chữ tương đồng ở gần nhau. agy nhận nội dung chữ, vị trí, thời điểm và toàn bộ lời thoại Trung/Việt để phân loại: phụ đề lời nói chỉ mờ; nhãn/tiêu đề/chú thích thì mờ và đè tiếng Việt; chữ Trung không đủ chắc để dịch vẫn được che trong chế độ đầy đủ, chỉ không bịa nhãn Việt. Nội dung OCR này cũng được gửi qua agy. Gaussian blur chỉ áp dụng quanh vùng chữ đang xuất hiện; nhãn Việt dùng font Arial có dấu, tự xuống dòng và co cỡ chữ. Video bật xử lý chữ phải mã hóa lại H.264/AAC; bản tắt giữ nhánh ghép hình cũ.

`screen_text/tracks_v3.json` lưu nhận diện; `classified_v3.json` lưu phân loại và bản dịch; `screen.log` lưu log. Hiện chưa có trình sửa vùng bằng tay. Các vùng OCR có độ tin cậy từ 0.25 và cả chữ xuất hiện thoáng qua vẫn có mặt nạ; vùng che lấy bao hợp các hộp lân cận và mở rộng viền để che nét chữ có hiệu ứng. Bản xuất được OCR lại ở 30 frame/giây (kiểm tra cả chữ lóe lên trong chuyển cảnh), nếu còn thấy cụm chữ Trung thì che bổ sung và kiểm tra lại; `screen_qc.json` lưu kết quả. OCR vẫn có thể bỏ sót chữ không nhận ra hoàn toàn; phân loại tự động có thể sai. Kiểm tra bản xuất trước khi dùng. Không tự che cả dải dưới màn hình khi video không có phụ đề.

Hai clip QA 15 giây tại `data/visual_text_qa/subtitles/` và `data/visual_text_qa/graphics/`, có video gốc, âm thanh Việt dùng lại và `video_chu_viet.mp4`.

## Kiểu chữ và độ ổn định trên hình

Bộ dựng chữ dùng một “lần xuất hiện” cho mỗi nhãn: gộp các biến thể OCR trùng/thiếu một phần, chọn quan sát đầy đủ nhất làm chuẩn. Font, số dòng, cỡ chữ và ảnh chữ được tính một lần rồi khóa; nhiễu OCR không làm đổi kích thước. Các nhãn khác nhau ở cùng vị trí thay nhau hiển thị, không chồng trong thời gian OCR nhận cả hai. Vị trí cố định theo trung vị; chỉ bám chuyển động khi có dịch chuyển đủ lớn và đã làm mượt.

Chữ Việt có nền trong suốt, chữ đậm và viền lấy gần màu chữ gốc. Đây là ước lượng, không xác định được chính xác font Trung ban đầu. Không kéo giãn bitmap chữ. Ưu tiên một dòng, chỉ xuống hai dòng khi cần.

Phần che không dùng ô đen/mosaic lớn nữa: phát hiện phần nét sáng, tối hoặc màu có tương phản trong vùng OCR, giãn mặt nạ vài pixel quanh viền, rồi dùng inpainting cục bộ. Với phụ đề, làm mềm phần nền đã phục hồi và feather mặt nạ. Nền có hoa văn, bàn tay hoặc vật chuyển động vẫn có thể bị nhòe nhẹ, chưa tương đương phục hồi nền bằng mô hình video chuyên dụng. File `.layout.json` cạnh video lưu font/cỡ/vị trí cố định để kiểm tra. OCR và bản dịch được dùng lại khi thử bộ dựng mới.
