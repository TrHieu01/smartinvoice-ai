"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { Session } from "@supabase/supabase-js";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  CloudUpload,
  FileCheck2,
  FileText,
  FolderOpen,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Plus,
  ReceiptText,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wallet,
  X,
} from "lucide-react";
import {
  api,
  categories,
  configured,
  formatDate,
  formatMoney,
  statusNames,
  supabase,
  type Analytics,
  type Data,
  type Detail,
  type ReceiptList,
  type Summary,
} from "@/lib/client";
import { sampleAnalytics, sampleDetail, samples } from "@/lib/demo";

type View = "dashboard" | "receipts" | "upload";
const fields: [keyof Omit<Data, "items">, string, string][] = [
  ["merchant", "Cửa hàng", "text"],
  ["purchase_date", "Ngày mua", "date"],
  ["invoice_number", "Số hóa đơn", "text"],
  ["merchant_tax_id", "Mã số thuế", "text"],
  ["subtotal", "Tiền hàng", "number"],
  ["tax_amount", "Thuế", "number"],
  ["discount_amount", "Giảm giá", "number"],
  ["total_amount", "Tổng thanh toán", "number"],
];

export default function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [demo, setDemo] = useState(false);
  const [view, setView] = useState<View>("dashboard");
  const [list, setList] = useState<ReceiptList>({
    items: [],
    page: 1,
    page_size: 10,
    total_count: 0,
  });
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [merchant, setMerchant] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [sort, setSort] = useState("created_at_desc");
  const [page, setPage] = useState(1);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<{
    id: string;
    key: string;
  } | null>(null);
  const [uploadStep, setUploadStep] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!configured) {
      setAuthReady(true);
      return;
    }
    const { data } = supabase().auth.onAuthStateChange((event, value) => {
      setSession(value);
      setAuthReady(true);
      if (value) setDemo(false);
      if (event === "SIGNED_IN" || event === "SIGNED_OUT") {
        setSelected(null);
        setList({ items: [], total_count: 0, page: 1, page_size: 10 });
        setAnalytics(null);
        setView("dashboard");
      }
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const refresh = useCallback(async () => {
    if (demo) {
      setList({
        items: samples.filter(
          (r) =>
            (!merchant ||
              r.merchant?.toLowerCase().includes(merchant.toLowerCase())) &&
            (!status || r.status === status),
        ),
        page: 1,
        page_size: 10,
        total_count: samples.length,
      });
      setAnalytics(sampleAnalytics);
      return;
    }
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({
        page: String(page),
        page_size: "10",
        sort,
      });
      for (const [key, value] of Object.entries({
        merchant,
        status,
        date_from: from,
        date_to: to,
        min_amount: min,
        max_amount: max,
      }))
        if (value) query.set(key, value);
      const today = new Date();
      const end = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      const start = `${today.getFullYear()}-01-01`;
      const [receipts, stats] = await Promise.all([
        api<ReceiptList>(`/receipts?${query}`),
        api<Analytics>(`/analytics/summary?date_from=${start}&date_to=${end}`),
      ]);
      setList(receipts);
      setAnalytics(stats);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session, demo, merchant, status, from, to, min, max, sort, page]);
  useEffect(() => {
    const timer = setTimeout(() => {
      void refresh();
    }, 300);
    return () => clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    if (
      demo ||
      !selected ||
      !["queued", "processing"].includes(selected.status)
    )
      return;
    let stopped = false;
    let delay = 2000;
    const deadline = Date.now() + 15 * 60_000;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<{ status: string }>(
          `/receipts/${selected.id}/status`,
        );
        if (!stopped && result.status !== selected.status) {
          const detail = await api<Detail>(`/receipts/${selected.id}`);
          if (!stopped) {
            setSelected(detail);
            void refresh();
          }
        }
      } catch (err) {
        if (!stopped) setError((err as Error).message);
      }
      if (!stopped && Date.now() < deadline) {
        delay = Math.min(delay * 1.6, 30_000);
        timer = setTimeout(poll, delay);
      } else if (!stopped) {
        setError(
          "Xử lý lâu hơn dự kiến. Bạn có thể mở lại hóa đơn từ lịch sử để kiểm tra sau.",
        );
      }
    }
    timer = setTimeout(poll, delay);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [selected?.id, selected?.status, demo, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  async function open(row: Summary) {
    setError("");
    if (demo) {
      setSelected(sampleDetail(row));
      return;
    }
    setBusy(true);
    try {
      setSelected(await api<Detail>(`/receipts/${row.id}`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function navigate(next: View) {
    setSelected(null);
    setView(next);
    setError("");
    setNotice("");
  }

  async function upload(file: File) {
    if (demo) {
      setNotice(
        "Hãy đăng nhập để tải hóa đơn của bạn. Dữ liệu minh họa chỉ dùng để xem giao diện.",
      );
      return;
    }
    setError("");
    setNotice("");
    if (
      !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(
        file.type,
      ) ||
      file.size > 5_000_000 ||
      file.size === 0
    ) {
      setError("Chọn JPG, PNG, WebP hoặc PDF, dung lượng từ 1 byte đến 5 MB.");
      return;
    }
    setBusy(true);
    setUploadStep("Tạo lượt tải lên…");
    setLastUpload(null);
    try {
      const ticket = await api<{
        id: string;
        upload: { path: string; token: string };
      }>("/receipts", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type,
          size_bytes: file.size,
        }),
      });
      setUploadStep("Đang tải file…");
      const { error: uploadError } = await supabase()
        .storage.from("receipts")
        .uploadToSignedUrl(ticket.upload.path, ticket.upload.token, file, {
          contentType: file.type,
        });
      if (uploadError)
        throw new Error(
          "Tải file chưa thành công. Bạn có thể xóa bản ghi chờ trong lịch sử và thử lại.",
        );
      const submission = { id: ticket.id, key: crypto.randomUUID() };
      setLastUpload(submission);
      setUploadStep("Kiểm tra file và đưa vào hàng đợi…");
      await api(`/receipts/${submission.id}/submit`, {
        method: "POST",
        headers: { "Idempotency-Key": submission.key },
      });
      setLastUpload(null);
      setSelected(await api<Detail>(`/receipts/${submission.id}`));
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setUploadStep("");
      if (input.current) input.current.value = "";
    }
  }
  async function retrySubmit() {
    if (!lastUpload) return;
    setBusy(true);
    setError("");
    try {
      await api(`/receipts/${lastUpload.id}/submit`, {
        method: "POST",
        headers: { "Idempotency-Key": lastUpload.key },
      });
      setSelected(await api<Detail>(`/receipts/${lastUpload.id}`));
      setLastUpload(null);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!deleteId || demo) return;
    setBusy(true);
    setError("");
    try {
      await api(`/receipts/${deleteId}`, { method: "DELETE" });
      if (selected?.id === deleteId) setSelected(null);
      setDeleteId(null);
      await refresh();
      setNotice(
        "Hóa đơn đã được ẩn. File sẽ được dọn sau khi đường dẫn tải lên hết hạn.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!authReady)
    return (
      <div className="boot">
        <LoaderCircle className="spin" /> Đang mở SmartInvoice…
      </div>
    );
  if (!session && !demo)
    return (
      <Auth
        onDemo={() => {
          setDemo(true);
          setError("");
        }}
      />
    );
  const pending = list.items.filter((r) => r.status === "needs_review").length;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("dashboard");
          }}
        >
          <span className="brand-icon">
            <ReceiptText size={23} />
          </span>
          <span>
            SmartInvoice<span className="brand-ai"> AI</span>
          </span>
        </a>
        <div className="workspace-label">KHÔNG GIAN CÁ NHÂN</div>
        <nav aria-label="Điều hướng chính">
          <button
            className={
              view === "dashboard" && !selected ? "nav-item active" : "nav-item"
            }
            onClick={() => navigate("dashboard")}
          >
            <LayoutDashboard size={19} /> Tổng quan
          </button>
          <button
            className={
              view === "receipts" || selected ? "nav-item active" : "nav-item"
            }
            onClick={() => navigate("receipts")}
          >
            <FolderOpen size={19} /> Hóa đơn của tôi{" "}
            <span className="nav-count">{list.total_count}</span>
          </button>
          <button
            className={
              view === "upload" && !selected ? "nav-item active" : "nav-item"
            }
            onClick={() => navigate("upload")}
          >
            <CloudUpload size={19} /> Tải hóa đơn
          </button>
        </nav>
        <div className="sidebar-tip">
          <span className="tip-icon">
            <Sparkles size={20} />
          </span>
          <strong>
            Nhẹ việc giấy tờ.
            <br />
            Rõ từng khoản chi.
          </strong>
          <p>
            Từ hóa đơn đến dữ liệu,
            <br />
            AI giúp bạn một tay.
          </p>
          <button onClick={() => navigate("upload")}>
            Thử tải hóa đơn <ArrowUpRight size={15} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <ShieldCheck size={16} /> Hóa đơn của bạn được lưu riêng tư
        </div>
        <button
          className="profile"
          onClick={async () => {
            if (demo) setDemo(false);
            else {
              await supabase().auth.signOut();
              setSelected(null);
              setList({ items: [], total_count: 0, page: 1, page_size: 10 });
            }
          }}
        >
          <span className="avatar">
            {demo ? "M" : session?.user.email?.[0]?.toUpperCase()}
          </span>
          <span>
            <strong>
              {demo ? "Không gian mẫu" : session?.user.email?.split("@")[0]}
            </strong>
            <small>{demo ? "Đăng nhập tài khoản" : "Tài khoản cá nhân"}</small>
          </span>
          <LogOut size={16} />
        </button>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div>
            <span className="breadcrumb">Không gian làm việc</span>
            <ChevronRight size={14} />
            <strong>
              {selected
                ? "Kiểm tra hóa đơn"
                : view === "dashboard"
                  ? "Tổng quan"
                  : view === "receipts"
                    ? "Hóa đơn"
                    : "Tải hóa đơn"}
            </strong>
          </div>
          <span className="private-pill">
            <span /> {demo ? "Dữ liệu minh họa" : "Không gian riêng tư"}
          </span>
        </header>
        {demo && (
          <div className="demo-banner">
            Bạn đang xem dữ liệu minh họa, chưa kết nối hóa đơn thật.{" "}
            <button onClick={() => setDemo(false)}>
              Đăng nhập <ArrowRight size={14} />
            </button>
          </div>
        )}
        <main>
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button
                aria-label="Đóng thông báo lỗi"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert" role="status">
              {notice}
              <button aria-label="Đóng thông báo" onClick={() => setNotice("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {selected ? (
            <Review
              detail={selected}
              demo={demo}
              onBack={() => {
                setSelected(null);
                void refresh();
              }}
              onUpdate={(row) => {
                setSelected(row);
                void refresh();
              }}
              onError={setError}
              onDelete={() => setDeleteId(selected.id)}
            />
          ) : view === "upload" ? (
            <>
              <PageHeading
                eyebrow="THÊM MỘT HÓA ĐƠN"
                title="Để AI đọc giúp bạn."
                subtitle="Tải file lên, kiểm tra thông tin, rồi lưu vào không gian chi tiêu của bạn."
              />
              <section
                className="upload-panel"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (!busy && e.dataTransfer.files[0])
                    void upload(e.dataTransfer.files[0]);
                }}
              >
                <div className="upload-orbit">
                  <CloudUpload size={38} />
                </div>
                <h2>Kéo hóa đơn vào đây</h2>
                <p>Ảnh chụp rõ nét hoặc bản PDF của bạn</p>
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => input.current?.click()}
                >
                  {busy ? (
                    <LoaderCircle size={17} className="spin" />
                  ) : (
                    <Plus size={17} />
                  )}{" "}
                  {busy ? uploadStep : "Chọn file từ máy"}
                </button>
                <small>
                  JPG, PNG, WebP, PDF · Tối đa 5 MB · PDF tối đa 5 trang
                </small>
                <input
                  ref={input}
                  type="file"
                  accept="image/jpeg,image/png,image/webp,application/pdf"
                  hidden
                  onChange={(e) => {
                    if (e.target.files?.[0]) void upload(e.target.files[0]);
                  }}
                />
              </section>
              {lastUpload && (
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => void retrySubmit()}
                >
                  <RefreshCw size={16} /> Thử gửi lại file đã tải
                </button>
              )}
              <div className="steps">
                {[
                  ["01", "Tải hóa đơn", "Một file ảnh hoặc PDF"],
                  ["02", "AI trích xuất", "Đọc cửa hàng, ngày, số tiền"],
                  ["03", "Bạn xác nhận", "Đối chiếu và sửa trước khi lưu"],
                ].map(([num, title, desc]) => (
                  <div key={num}>
                    <span>{num}</span>
                    <div>
                      <strong>{title}</strong>
                      <p>{desc}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="privacy-note">
                <ShieldCheck size={20} />
                <p>
                  File được lưu riêng tư. Kết quả AI luôn cần bạn kiểm tra trước
                  khi được tính vào tổng chi tiêu.
                </p>
              </div>
            </>
          ) : (
            <>
              <PageHeading
                eyebrow={
                  view === "dashboard"
                    ? "MỌI KHOẢN CHI, MỘT NƠI"
                    : "NGĂN NẮP TỪNG CHỨNG TỪ"
                }
                title={
                  view === "dashboard"
                    ? "Bức tranh chi tiêu của bạn."
                    : "Hóa đơn của tôi"
                }
                subtitle={
                  view === "dashboard"
                    ? "Ít nhập liệu hơn. Nhiều thời gian hơn cho những điều quan trọng."
                    : "Tìm, kiểm tra và quản lý những hóa đơn đã tải lên."
                }
                action={
                  <button
                    className="button primary"
                    onClick={() => navigate("upload")}
                  >
                    <Plus size={18} /> Tải hóa đơn
                  </button>
                }
              />
              {view === "dashboard" && (
                <>
                  <div className="stat-grid">
                    <Stat
                      title="Tổng chi tiêu năm nay"
                      value={formatMoney(analytics?.total_amount ?? "0")}
                      note="Từ các hóa đơn đã xác nhận"
                      icon={<Wallet size={21} />}
                      accent
                    />
                    <Stat
                      title="Hóa đơn đã xác nhận"
                      value={String(analytics?.receipt_count ?? 0).padStart(
                        2,
                        "0",
                      )}
                      note="Đã đưa vào thống kê chi tiêu"
                      icon={<FileCheck2 size={21} />}
                    />
                    <Stat
                      title="Cần kiểm tra"
                      value={String(pending).padStart(2, "0")}
                      note="Trong các hóa đơn đang hiển thị"
                      icon={<ReceiptText size={21} />}
                    />
                  </div>
                  <div className="chart-grid">
                    <section className="panel chart-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Chi tiêu theo tháng</h2>
                          <p>Chỉ tính hóa đơn đã xác nhận</p>
                        </div>
                        <span className="subtle-label">VND</span>
                      </div>
                      <SpendChart analytics={analytics} />
                    </section>
                    <section className="panel category-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Tiền đi đâu?</h2>
                          <p>Chi tiêu theo danh mục</p>
                        </div>
                        <ArrowUpRight size={20} />
                      </div>
                      <div className="category-list">
                        {analytics?.categories.length ? (
                          analytics.categories.map((cat, i) => (
                            <div key={cat.category}>
                              <span className={`category-dot dot-${i % 4}`} />
                              <span>{categories[cat.category]}</span>
                              <strong>{formatMoney(cat.total_amount)}</strong>
                              <div className="category-track">
                                <span
                                  style={{
                                    width: `${(Number(cat.total_amount) / Math.max(Number(analytics.total_amount), 1)) * 100}%`,
                                  }}
                                />
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="small-empty">
                            <BarChart3 size={28} />
                            <p>
                              Xác nhận hóa đơn đầu tiên
                              <br />
                              để bắt đầu xem thống kê.
                            </p>
                          </div>
                        )}
                      </div>
                    </section>
                  </div>
                </>
              )}
              <section className="panel receipts-panel">
                <div className="panel-heading">
                  <div>
                    <h2>
                      {view === "dashboard"
                        ? "Hóa đơn gần đây"
                        : "Tất cả hóa đơn"}{" "}
                      <span className="count-pill">{list.total_count}</span>
                    </h2>
                    <p>Mỗi hóa đơn là một khoản chi được ghi nhớ.</p>
                  </div>
                  {view === "dashboard" ? (
                    <button
                      className="text-button"
                      onClick={() => navigate("receipts")}
                    >
                      Xem tất cả <ArrowRight size={16} />
                    </button>
                  ) : (
                    <button
                      className="icon-button"
                      title="Tải lại"
                      onClick={() => void refresh()}
                      disabled={loading}
                    >
                      <RefreshCw className={loading ? "spin" : ""} size={18} />
                    </button>
                  )}
                </div>
                {view === "receipts" && (
                  <div className="filters">
                    <label className="search">
                      <Search size={17} />
                      <input
                        aria-label="Tìm cửa hàng"
                        placeholder="Tìm tên cửa hàng…"
                        value={merchant}
                        onChange={(e) => {
                          setMerchant(e.target.value);
                          setPage(1);
                        }}
                      />
                    </label>
                    <select
                      aria-label="Trạng thái"
                      value={status}
                      onChange={(e) => {
                        setStatus(e.target.value);
                        setPage(1);
                      }}
                    >
                      <option value="">Mọi trạng thái</option>
                      {Object.entries(statusNames)
                        .filter(([key]) => key !== "deleting")
                        .map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                    </select>
                    <select
                      aria-label="Sắp xếp"
                      value={sort}
                      onChange={(e) => {
                        setSort(e.target.value);
                        setPage(1);
                      }}
                    >
                      <option value="created_at_desc">Mới tải lên</option>
                      <option value="purchase_date_desc">
                        Ngày mua gần nhất
                      </option>
                      <option value="total_amount_desc">
                        Số tiền cao nhất
                      </option>
                    </select>
                    <label>
                      Từ ngày
                      <input
                        type="date"
                        value={from}
                        onChange={(e) => {
                          setFrom(e.target.value);
                          setPage(1);
                        }}
                      />
                    </label>
                    <label>
                      Đến ngày
                      <input
                        type="date"
                        value={to}
                        onChange={(e) => {
                          setTo(e.target.value);
                          setPage(1);
                        }}
                      />
                    </label>
                    <input
                      aria-label="Số tiền tối thiểu"
                      type="number"
                      min="0"
                      placeholder="Tiền tối thiểu"
                      value={min}
                      onChange={(e) => {
                        setMin(e.target.value);
                        setPage(1);
                      }}
                    />
                    <input
                      aria-label="Số tiền tối đa"
                      type="number"
                      min="0"
                      placeholder="Tiền tối đa"
                      value={max}
                      onChange={(e) => {
                        setMax(e.target.value);
                        setPage(1);
                      }}
                    />
                  </div>
                )}
                {loading ? (
                  <div className="table-loading">
                    <LoaderCircle className="spin" size={22} /> Đang tải hóa
                    đơn…
                  </div>
                ) : list.items.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>CỬA HÀNG / HÓA ĐƠN</th>
                          <th>NGÀY MUA</th>
                          <th>DANH MỤC</th>
                          <th>TRẠNG THÁI</th>
                          <th className="align-right">SỐ TIỀN</th>
                          <th>
                            <span className="sr-only">Thao tác</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.items.map((row, index) => (
                          <tr key={row.id}>
                            <td>
                              <button
                                className="merchant-button"
                                disabled={busy}
                                onClick={() => void open(row)}
                              >
                                <span
                                  className={`merchant-icon merchant-${index % 4}`}
                                >
                                  {row.merchant?.[0] ?? <FileText size={19} />}
                                </span>
                                <span>
                                  <strong>
                                    {row.merchant ?? row.filename}
                                  </strong>
                                  <small>
                                    {row.merchant
                                      ? row.filename
                                      : "Chưa có thông tin cửa hàng"}
                                  </small>
                                </span>
                              </button>
                            </td>
                            <td>{formatDate(row.purchase_date)}</td>
                            <td>
                              <span className="category-label">
                                {categories[row.category]}
                              </span>
                            </td>
                            <td>
                              <Badge status={row.status} />
                            </td>
                            <td className="align-right amount">
                              {formatMoney(row.total_amount)}
                            </td>
                            <td>
                              <button
                                className="icon-button"
                                title="Xem hóa đơn"
                                onClick={() => void open(row)}
                              >
                                <ArrowUpRight size={18} />
                              </button>
                              {!demo && (
                                <button
                                  className="icon-button danger"
                                  title="Xóa hóa đơn"
                                  onClick={() => setDeleteId(row.id)}
                                >
                                  <Trash2 size={15} />
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="empty-state">
                    <span>
                      <ReceiptText size={32} />
                    </span>
                    <h3>
                      {merchant || status || from || to || min || max
                        ? "Chưa tìm thấy hóa đơn phù hợp"
                        : "Khoản chi đầu tiên bắt đầu ở đây"}
                    </h3>
                    <p>
                      {merchant || status
                        ? "Thử thay đổi bộ lọc để xem kết quả khác."
                        : "Tải hóa đơn lên và để AI giúp bạn nhập liệu."}
                    </p>
                    <button
                      className="button"
                      onClick={() => navigate("upload")}
                    >
                      <Plus size={16} /> Tải hóa đơn đầu tiên
                    </button>
                  </div>
                )}
                <div className="table-footer">
                  <span>
                    {list.items.length} / {list.total_count} hóa đơn
                  </span>
                  <div>
                    <button
                      aria-label="Trang trước"
                      disabled={page === 1 || demo}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <span>Trang {page}</span>
                    <button
                      aria-label="Trang sau"
                      disabled={page * 10 >= list.total_count || demo}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </div>
              </section>
              <div className="footer-note">
                <ShieldCheck size={14} /> Riêng tư từ file gốc đến kết quả cuối
                cùng.<span>SmartInvoice AI</span>
              </div>
            </>
          )}
        </main>
      </div>
      {deleteId && (
        <div className="modal-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-title"
            className="modal"
          >
            <span className="delete-icon">
              <Trash2 size={24} />
            </span>
            <h2 id="delete-title">Xóa hóa đơn này?</h2>
            <p>
              Hóa đơn sẽ được gỡ khỏi lịch sử và thống kê. File gốc cùng dữ liệu
              sẽ được dọn theo lịch.
            </p>
            <div>
              <button
                className="button"
                disabled={busy}
                onClick={() => setDeleteId(null)}
              >
                Giữ lại
              </button>
              <button
                className="button destructive"
                disabled={busy}
                onClick={() => void remove()}
              >
                {busy ? "Đang xóa…" : "Xóa hóa đơn"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function PageHeading({
  eyebrow,
  title,
  subtitle,
  action,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {action}
    </div>
  );
}
function Stat({
  title,
  value,
  note,
  icon,
  accent = false,
}: {
  title: string;
  value: string;
  note: string;
  icon: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <section className={`stat ${accent ? "stat-accent" : ""}`}>
      <div>
        <span>{title}</span>
        <span className="stat-icon">{icon}</span>
      </div>
      <strong>{value}</strong>
      <p>
        <span className="tiny-dot" />
        {note}
      </p>
    </section>
  );
}
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`}>
      <span />
      {statusNames[status] ?? status}
    </span>
  );
}
function SpendChart({ analytics }: { analytics: Analytics | null }) {
  const values = analytics?.monthly.slice(-8) ?? [];
  const maximum = Math.max(...values.map((m) => Number(m.total_amount)), 1);
  return (
    <div className="spend-chart">
      {!values.some((m) => Number(m.total_amount) > 0) && (
        <span className="chart-placeholder">Chưa có chi tiêu đã xác nhận</span>
      )}
      <div className="chart-gridlines">
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="chart-bars">
        {(values.length
          ? values
          : Array.from({ length: 6 }, (_, i) => ({
              month: `Tháng ${i + 1}`,
              total_amount: "0",
            }))
        ).map((month, i) => (
          <div className="chart-column" key={month.month}>
            <div
              className={`chart-bar ${i === values.length - 1 ? "latest" : ""}`}
              style={{
                height: `${Math.max((Number(month.total_amount) / maximum) * 138, 3)}px`,
              }}
              tabIndex={0}
              aria-label={`${month.month}: ${formatMoney(month.total_amount)}`}
            >
              <span>{formatMoney(month.total_amount)}</span>
            </div>
            <small>
              {month.month.includes("-")
                ? `Thg ${Number(month.month.slice(-2))}`
                : month.month}
            </small>
          </div>
        ))}
      </div>
    </div>
  );
}

function Auth({ onDemo }: { onDemo: () => void }) {
  const [signup, setSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (!configured)
        throw new Error(
          "Đăng nhập chưa được cấu hình. Bạn có thể xem không gian mẫu bên dưới.",
        );
      const { error, data } = signup
        ? await supabase().auth.signUp({
            email,
            password,
            options: { emailRedirectTo: location.origin },
          })
        : await supabase().auth.signInWithPassword({ email, password });
      if (error)
        throw new Error(
          signup
            ? "Chưa tạo được tài khoản. Hãy kiểm tra email, mật khẩu hoặc thử lại sau."
            : "Chưa đăng nhập được. Hãy kiểm tra email, mật khẩu và xác nhận email của bạn.",
        );
      if (signup && !data.session)
        setMessage(
          "Đã gửi email xác nhận. Hãy mở email để kích hoạt tài khoản rồi đăng nhập.",
        );
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <section className="auth-story">
        <div className="brand">
          <span className="brand-icon">
            <ReceiptText size={24} />
          </span>
          <span>SmartInvoice AI</span>
        </div>
        <div className="auth-copy">
          <div className="eyebrow">HÓA ĐƠN NHỎ. BỨC TRANH LỚN.</div>
          <h1>
            Giữ hóa đơn.
            <br />
            Hiểu khoản chi.
            <br />
            <em>Nhẹ đầu hơn.</em>
          </h1>
          <p>
            Biến những tờ hóa đơn thành thông tin hữu ích.
            <br />
            AI đọc giúp, bạn kiểm tra và quyết định.
          </p>
          <div className="auth-receipt">
            <span className="receipt-check">
              <Check size={22} />
            </span>
            <span className="receipt-line wide" />
            <span className="receipt-line" />
            <div>
              <span>Tiền hàng</span>
              <strong>125.000 ₫</strong>
            </div>
            <div>
              <span>Thuế</span>
              <strong>10.000 ₫</strong>
            </div>
            <div className="receipt-total">
              <strong>Tổng thanh toán</strong>
              <strong>135.000 ₫</strong>
            </div>
            <span className="receipt-caption">
              <Sparkles size={13} /> Minh họa dữ liệu được AI trích xuất
            </span>
          </div>
        </div>
        <div className="auth-proof">
          <ShieldCheck size={17} /> Riêng tư · Có thể chỉnh sửa · Bạn luôn kiểm
          soát
        </div>
      </section>
      <section className="auth-form-wrap">
        <div className="auth-form">
          <span className="auth-kicker">CHÀO BẠN,</span>
          <h2>{signup ? "Bắt đầu ngăn nắp hơn." : "Chào mừng trở lại."}</h2>
          <p>
            {signup
              ? "Tạo không gian riêng cho những hóa đơn của bạn."
              : "Mở không gian hóa đơn và chi tiêu của bạn."}
          </p>
          <form onSubmit={submit}>
            <label>
              Email
              <input
                type="email"
                autoComplete="email"
                required
                placeholder="ban@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Mật khẩu
              <input
                type="password"
                autoComplete={signup ? "new-password" : "current-password"}
                minLength={8}
                required
                placeholder="Ít nhất 8 ký tự"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {message && (
              <div className="auth-message" role="status">
                {message}
              </div>
            )}
            <button className="button primary" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={18} /> : null}
              {signup ? "Tạo tài khoản" : "Đăng nhập"}
              <ArrowRight size={17} />
            </button>
          </form>
          <p className="auth-toggle">
            {signup ? "Đã có tài khoản?" : "Chưa có tài khoản?"}{" "}
            <button
              onClick={() => {
                setSignup(!signup);
                setMessage("");
              }}
            >
              {signup ? "Đăng nhập" : "Đăng ký miễn phí"}
            </button>
          </p>
          <div className="auth-divider">
            <span />
            hoặc khám phá trước
            <span />
          </div>
          <button className="button demo-button" onClick={onDemo}>
            <LayoutDashboard size={17} /> Xem không gian mẫu{" "}
            <ArrowUpRight size={16} />
          </button>
          <small className="auth-small">
            Không cần tài khoản · Chỉ chứa dữ liệu minh họa
          </small>
        </div>
        <span className="auth-foot">
          Một nơi gọn gàng hơn cho những khoản chi thường ngày.
        </span>
      </section>
    </div>
  );
}

function Review({
  detail,
  demo,
  onBack,
  onUpdate,
  onError,
  onDelete,
}: {
  detail: Detail;
  demo: boolean;
  onBack: () => void;
  onUpdate: (detail: Detail) => void;
  onError: (message: string) => void;
  onDelete: () => void;
}) {
  const [data, setData] = useState<Data>(structuredClone(detail.data));
  const [category, setCategory] = useState(detail.category);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [field, setField] = useState("/merchant");
  useEffect(() => {
    setData(structuredClone(detail.data));
    setCategory(detail.category);
  }, [detail]);
  useEffect(() => {
    setUrl("");
    if (demo || detail.status === "awaiting_upload") return;
    let stopped = false;
    async function load() {
      try {
        const result = await api<{ url: string }>(
          `/receipts/${detail.id}/file`,
        );
        if (!stopped) setUrl(result.url);
      } catch (err) {
        if (!stopped) onError((err as Error).message);
      }
    }
    void load();
    const timer = setInterval(() => {
      void load();
    }, 240000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [detail.id, demo, detail.status, onError]);
  const reviewable = ["needs_review", "confirmed"].includes(detail.status);
  const ids =
    detail.latest_extraction?.evidence.find((e) => e.field === field)
      ?.line_ids ?? [];
  const source =
    detail.latest_extraction?.ocr.pages.flatMap((page) =>
      page.lines
        .filter((line) => ids.includes(line.id))
        .map((line) => ({ ...line, page: page.page_number })),
    ) ?? [];
  async function save(action: "save" | "confirm") {
    if (demo) return;
    setBusy(true);
    onError("");
    try {
      onUpdate(
        await api<Detail>(`/receipts/${detail.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            expected_version: detail.version,
            action,
            data,
            category,
          }),
        }),
      );
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function retry() {
    setBusy(true);
    onError("");
    try {
      await api(`/receipts/${detail.id}/retry`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      onUpdate(await api<Detail>(`/receipts/${detail.id}`));
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button className="back-button" onClick={onBack}>
        <ArrowLeft size={17} /> Quay lại hóa đơn
      </button>
      <div className="review-heading">
        <div>
          <h1>{detail.merchant ?? detail.filename}</h1>
          <p>
            {detail.filename} <span>·</span> <Badge status={detail.status} />
          </p>
        </div>
        {!demo && (
          <button className="button danger" onClick={onDelete}>
            <Trash2 size={16} /> Xóa
          </button>
        )}
      </div>
      {!reviewable && (
        <div className="processing-panel">
          {detail.status === "failed" ? (
            <>
              <CircleHelp size={26} />
              <div>
                <strong>Chưa xử lý được hóa đơn</strong>
                <p>
                  Mã lỗi: {detail.job?.error_code ?? "processing_failed"}. Bạn
                  có thể thử lại.
                </p>
              </div>
              <button
                className="button"
                disabled={busy}
                onClick={() => void retry()}
              >
                <RefreshCw size={16} /> Thử lại
              </button>
            </>
          ) : (
            <>
              <LoaderCircle className="spin" size={26} />
              <div>
                <strong>
                  {detail.status === "awaiting_upload"
                    ? "File chưa được tải lên"
                    : "AI đang chuẩn bị thông tin cho bạn"}
                </strong>
                <p>
                  {detail.status === "awaiting_upload"
                    ? "Quay lại mục tải hóa đơn để tạo lượt tải mới."
                    : "Bạn có thể rời màn hình này và xem kết quả sau trong lịch sử."}
                </p>
              </div>
            </>
          )}
        </div>
      )}
      <div className="review-grid">
        <section className="panel original-panel">
          <div className="panel-heading">
            <h2>
              <FileText size={17} /> Hóa đơn gốc
            </h2>
            <span className="subtle-label">ĐỐI CHIẾU</span>
          </div>
          <div className="document-preview">
            {demo ? (
              <div className="sample-paper">
                <span className="eyebrow">BẢN MINH HỌA</span>
                <h3>{detail.merchant}</h3>
                <p>HÓA ĐƠN BÁN HÀNG</p>
                <hr />
                <p>Ngày: {formatDate(data.purchase_date)}</p>
                <p>Số hóa đơn: DEMO-001</p>
                <hr />
                <div>
                  <span>Tổng thanh toán</span>
                  <strong>{formatMoney(data.total_amount)}</strong>
                </div>
                <hr />
                <small>Cảm ơn quý khách!</small>
                <span className="paper-watermark">DỮ LIỆU MẪU</span>
              </div>
            ) : url ? (
              detail.filename.toLowerCase().endsWith(".pdf") ? (
                <iframe
                  title="Hóa đơn PDF gốc"
                  src={url}
                  sandbox="allow-same-origin"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="image-container">
                  <img
                    src={url}
                    alt="Hóa đơn gốc đã tải lên"
                    referrerPolicy="no-referrer"
                  />
                  {source
                    .filter((line) => line.page === 1)
                    .map((line) => (
                      <span
                        key={line.id}
                        className="evidence-box"
                        style={{
                          left: `${line.bbox.x0 * 100}%`,
                          top: `${line.bbox.y0 * 100}%`,
                          width: `${(line.bbox.x1 - line.bbox.x0) * 100}%`,
                          height: `${(line.bbox.y1 - line.bbox.y0) * 100}%`,
                        }}
                      />
                    ))}
                </div>
              )
            ) : (
              <div className="small-empty">
                <FileText size={34} />
                <p>
                  {detail.status === "awaiting_upload"
                    ? "Chưa có file gốc"
                    : "Đang tải bản gốc…"}
                </p>
              </div>
            )}
          </div>
          <div className="source-evidence">
            <strong>
              <Search size={14} /> Nguồn của trường đang chọn
            </strong>
            <p>
              {source.length
                ? source.map((line) => (
                    <span key={line.id}>
                      Trang {line.page}: {line.text}
                      <br />
                    </span>
                  ))
                : "Chọn một trường để xem dòng OCR tương ứng. Trường nhập thủ công có thể không có nguồn AI."}
            </p>
          </div>
        </section>
        <section className="panel extracted-panel">
          <div className="panel-heading">
            <div>
              <h2>
                <Sparkles size={18} /> Thông tin trích xuất
              </h2>
              <p>Đối chiếu với bản gốc trước khi xác nhận.</p>
            </div>
            <span className="ai-tag">AI + BẠN</span>
          </div>
          {detail.warnings.length > 0 && (
            <div className="review-warnings">
              {detail.warnings.map((warning, i) => (
                <p key={i}>
                  <CircleHelp size={14} />
                  {warning.message}
                </p>
              ))}
            </div>
          )}
          <fieldset
            disabled={!reviewable || busy || demo}
            className="review-fields"
          >
            <div className="field-grid">
              {fields.map(([key, label, type]) => (
                <label
                  key={key}
                  className={
                    key === "merchant" || key === "total_amount"
                      ? "field-wide"
                      : ""
                  }
                >
                  {label}
                  {["merchant", "purchase_date", "total_amount"].includes(
                    key,
                  ) && <span className="required-mark"> *</span>}
                  <input
                    type={type}
                    step={type === "number" ? "0.01" : undefined}
                    min={type === "number" ? "0" : undefined}
                    value={data[key] ?? ""}
                    placeholder="Chưa xác định"
                    onFocus={() => setField("/" + key)}
                    onChange={(e) =>
                      setData({ ...data, [key]: e.target.value || null })
                    }
                  />
                </label>
              ))}
              <label>
                Tiền tệ *
                <select
                  value={data.currency ?? ""}
                  onFocus={() => setField("/currency")}
                  onChange={(e) =>
                    setData({
                      ...data,
                      currency: e.target.value === "VND" ? "VND" : null,
                    })
                  }
                >
                  <option value="">Chưa xác định</option>
                  <option value="VND">VND — Việt Nam đồng</option>
                </select>
              </label>
              <label>
                Danh mục
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  {Object.entries(categories).map(([key, title]) => (
                    <option key={key} value={key}>
                      {title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="item-heading">
              <h3>Sản phẩm ({data.items.length})</h3>
              <button
                type="button"
                className="text-button"
                disabled={data.items.length >= 500}
                onClick={() =>
                  setData({
                    ...data,
                    items: [
                      ...data.items,
                      {
                        line_number: data.items.length + 1,
                        name: "",
                        quantity: null,
                        unit_price: null,
                        line_total: null,
                      },
                    ],
                  })
                }
              >
                <Plus size={15} /> Thêm dòng
              </button>
            </div>
            {data.items.map((item, index) => (
              <div className="item-editor" key={index}>
                <input
                  aria-label={`Tên sản phẩm ${index + 1}`}
                  placeholder="Tên sản phẩm"
                  value={item.name}
                  onFocus={() => setField(`/items/${index}/name`)}
                  onChange={(e) =>
                    setData({
                      ...data,
                      items: data.items.map((row, i) =>
                        i === index ? { ...row, name: e.target.value } : row,
                      ),
                    })
                  }
                />
                {(["quantity", "unit_price", "line_total"] as const).map(
                  (key, i) => (
                    <input
                      key={key}
                      aria-label={`${["Số lượng", "Đơn giá", "Thành tiền"][i]} ${index + 1}`}
                      placeholder={["SL", "Đơn giá", "Thành tiền"][i]}
                      type="number"
                      min="0"
                      step={key === "quantity" ? ".001" : ".01"}
                      value={item[key] ?? ""}
                      onFocus={() => setField(`/items/${index}/${key}`)}
                      onChange={(e) =>
                        setData({
                          ...data,
                          items: data.items.map((row, idx) =>
                            idx === index
                              ? { ...row, [key]: e.target.value || null }
                              : row,
                          ),
                        })
                      }
                    />
                  ),
                )}
                <button
                  type="button"
                  aria-label={`Xóa sản phẩm ${index + 1}`}
                  className="icon-button danger"
                  onClick={() =>
                    setData({
                      ...data,
                      items: data.items
                        .filter((_, i) => i !== index)
                        .map((row, i) => ({ ...row, line_number: i + 1 })),
                    })
                  }
                >
                  <X size={15} />
                </button>
              </div>
            ))}
            {!data.items.length && (
              <p className="muted item-note">
                Chưa có sản phẩm được trích xuất. Bạn có thể bổ sung khi cần.
              </p>
            )}
          </fieldset>
          <div className="review-actions">
            <p>
              <ShieldCheck size={15} />
              {demo
                ? "Dữ liệu mẫu chỉ để xem giao diện."
                : detail.status === "confirmed"
                  ? "Hóa đơn này đã có trong thống kê."
                  : "Chỉ cộng vào thống kê sau khi bạn xác nhận."}
            </p>
            <div>
              <button
                className="button"
                disabled={!reviewable || busy || demo}
                onClick={() => void save("save")}
              >
                Lưu chỉnh sửa
              </button>
              <button
                className="button primary"
                disabled={!reviewable || busy || demo}
                onClick={() => void save("confirm")}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <CheckCheck size={17} />
                )}{" "}
                Xác nhận hóa đơn
              </button>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
