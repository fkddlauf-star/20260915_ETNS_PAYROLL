(function () {
  const ACCENT = "#ec5117";
  const palette = ["#2f5e8f", "#6a3fa0", ACCENT, "#1a7f4b", "#8a5a00", "#756e66"];

  function renderCharts(data) {
    new Chart(document.getElementById("chartByType"), {
      type: "doughnut",
      data: {
        labels: data.by_type.map((r) => r.review_type),
        datasets: [{ data: data.by_type.map((r) => r.cnt), backgroundColor: palette }],
      },
      options: { plugins: { legend: { position: "bottom" } } },
    });

    new Chart(document.getElementById("chartByStatus"), {
      type: "bar",
      data: {
        labels: data.by_status.map((r) => r.status),
        datasets: [{ label: "건수", data: data.by_status.map((r) => r.cnt), backgroundColor: ACCENT }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    new Chart(document.getElementById("chartByDept"), {
      type: "bar",
      data: {
        labels: data.by_dept.map((r) => r.department),
        datasets: [{ label: "건수", data: data.by_dept.map((r) => r.cnt), backgroundColor: "#6a3fa0" }],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true } },
      },
    });

    new Chart(document.getElementById("chartTrend"), {
      type: "line",
      data: {
        labels: data.monthly_trend.map((r) => `${r.period_year}-${String(r.period_month).padStart(2, "0")}`),
        datasets: [
          {
            label: "발생 건수",
            data: data.monthly_trend.map((r) => r.cnt),
            borderColor: ACCENT,
            backgroundColor: "rgba(236,81,23,0.15)",
            fill: true,
            tension: 0.3,
          },
        ],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });
  }

  function refreshTiles() {
    fetch("/api/summary")
      .then((res) => res.json())
      .then((data) => {
        document.querySelectorAll("[data-key]").forEach((el) => {
          const key = el.dataset.key;
          if (!(key in data)) return;
          if (key === "mismatch_total") {
            el.textContent = Math.round(data[key]).toLocaleString() + "원";
          } else if (key === "completion_rate") {
            el.textContent = data[key] + "%";
          } else {
            el.textContent = data[key];
          }
        });
      })
      .catch(() => {});
  }

  renderCharts(chartData);
  setInterval(refreshTiles, 15000);
})();
