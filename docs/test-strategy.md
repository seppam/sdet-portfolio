# Strategi Testing: Struk Kilat

## 1. Apa yang paling berisiko?

Testing dimulai dari risiko, bukan dari tools. Risiko terbesar app ini:

| # | Risiko | Dampak | Layer yang menjaga |
|---|---|---|---|
| R1 | Total pengeluaran salah hitung | Reimburse salah: uang | Unit |
| R2 | Baris tidak valid lolos (tanggal ngawur, nominal negatif) | Data kotor | Unit |
| R3 | Job "hilang" atau nyangkut, user tidak pernah dapat hasil | User bingung, upload ulang | API + Integration |
| R4 | Kode kita salah memakai S3/SQS (format, retry, delete) | Pesan hilang / diproses dobel | Integration |
| R5 | UI tidak menampilkan hasil/error dengan benar | User tidak tahu ada masalah | E2E |

## 2. Piramida test

```
          /\        E2E (5)          lambat, mahal, sedikit: alur penting saja
         /  \
        /----\      Integration (8)  kode + boto3 + emulator AWS sungguhan
       /      \
      /--------\    API (19)         kontrak HTTP, pakai fake AWS (cepat)
     /          \
    /------------\  Unit (34)        aturan bisnis murni, ribuan kali per menit
```

Prinsipnya: **cek tiap hal di layer termurah yang bisa membuktikannya.** Contohnya, aturan
"nominal harus > 0" cukup dicek di unit test. Tidak perlu membuka browser untuk itu.

## 3. Teknik desain test

Teknik di bawah ini sama dengan yang dipakai di QA manual. Bedanya, hasilnya ditulis jadi kode.

- **Equivalence partitioning**: input dibagi ke kelompok yang perilakunya sama (nominal valid,
  negatif, desimal, teks), lalu satu wakil per kelompok dites.
  Lihat `test_parse_amount_invalid`.
- **Boundary value analysis**: tes tepat di batas: 1 dan `MAX_AMOUNT` (valid), 0 dan
  `MAX_AMOUNT+1` (tidak valid), deskripsi tepat 120 karakter, 1000 baris vs 1001 baris,
  file tepat 1 MB.
- **State transition**: status job `queued → processing → done/failed`. Tiap transisi dan
  jalur gagalnya dites, dan dua bug ditemukan di sini.
- **Error guessing**: skenario dari pengalaman QA: file Excel dengan BOM, file bukan UTF-8,
  baris duplikat beda huruf besar, pesan SQS rusak (poison message).

## 4. Test double vs emulator vs AWS asli

| Pilihan | Dipakai di | Kelebihan | Kekurangan |
|---|---|---|---|
| Fake di memori (`tests/fakes.py`) | API test | Super cepat, bisa simulasi "S3 down" | Hanya sebaik asumsi kita |
| Emulator (moto / mini-aws) | Integration, E2E | Perilaku boto3 asli, gratis, offline | Belum tentu 100% sama dengan AWS |
| AWS asli | (tidak dipakai) | Paling akurat | Biaya, kredensial, lambat |

BUG-002 adalah bukti kenapa butuh lebih dari satu layer: fake tidak meniru error
`NoSuchKey`, sehingga bug baru ketahuan di integration test.

## 5. Mencegah test flaky

- Tidak ada `time.sleep()` di E2E. Semua tunggu lewat `expect(...)` Playwright, yang otomatis
  retry sampai kondisi terpenuhi atau timeout.
- Tiap test integration dapat bucket dan queue dengan nama unik (UUID), jadi test tidak saling ganggu
  dan tidak butuh "reset" emulator.
- Tanggal "hari ini" disuntikkan (`today=`) di unit test, jadi hasil test tidak berubah besok.
- Selector E2E pakai `data-testid`, bukan teks atau CSS yang gampang berubah.
- Suite dijalankan 3× berturut-turut sebelum dianggap stabil.

## 6. Yang belum dites (sengaja)

Dicatat jujur supaya jelas batasannya:

- Beban/performa (rencana: k6 untuk `POST /api/uploads`).
- Keamanan (auth belum ada di app ini).
- Banyak worker paralel memproses pesan yang sama (perlu idempotency key).
- Kompatibilitas browser selain Chromium.

## 7. Definisi "selesai" untuk sebuah perubahan

1. `make test-fast` hijau di laptop.
2. Bug yang diperbaiki punya regression test yang **merah dulu** sebelum fix.
3. CI hijau di ketiga job (fast, integration ×2, e2e).
