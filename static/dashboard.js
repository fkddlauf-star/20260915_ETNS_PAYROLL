(function () {
  const palette = ["#3454d1", "#a34d00", "#a02463", "#1a7f4b", "#8a5a00", "#5c6b8a"];

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
        datasets: [{ label: "건수", data: data.by_status.map((r) => r.cnt), backgroundColor: "#3454d1" }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    new Chart(document.getElementById("chartByDept"), {
      type: "bar",
      data: {
        labels: data.by_dept.map((r) => r.department),
        datasets: [{ label: "건수", data: data.by_dept.map((r) => r.cnt), backgroundColor: "#a34d00" }],
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
            borderColor: "#3454d1",
            backgroundColor: "rgba(52,84,209,0.15)",
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
