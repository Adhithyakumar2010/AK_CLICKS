document.querySelector('.sidebar-toggle')?.addEventListener('click', () => {
  document.body.classList.toggle('sidebar-open');
});

const dashboardNav = document.querySelector('.customer-nav');
if (dashboardNav && !dashboardNav.querySelector('[data-home-link]')) {
  const homeLink = document.createElement('a');
  homeLink.href = '/';
  homeLink.dataset.homeLink = '';
  homeLink.innerHTML = '<i class="fa-solid fa-globe"></i>Return to Home';
  dashboardNav.appendChild(homeLink);
}

// Animate existing dashboard totals without changing the values rendered by Flask.
document.querySelectorAll('[data-counter]').forEach((counter) => {
  const target = Number(counter.dataset.counter || 0);
  if (!Number.isFinite(target) || target <= 0 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  counter.textContent = '0';
  const startedAt = performance.now();
  const duration = 550;
  const updateCounter = (now) => {
    const progress = Math.min((now - startedAt) / duration, 1);
    counter.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
    if (progress < 1) requestAnimationFrame(updateCounter);
  };
  requestAnimationFrame(updateCounter);
});

const dataNode = document.getElementById('customer-dashboard-data');
let dashboardData = {};
try {
  dashboardData = JSON.parse(dataNode?.textContent || '{}');
} catch (error) {
  dashboardData = {};
}

const setChartEmpty = (canvas, message) => {
  const shell = canvas?.closest('[data-chart-shell]');
  if (!shell) return;
  shell.classList.add('has-no-data');
  const empty = shell.querySelector('.chart-empty');
  if (empty) {
    empty.textContent = message;
    empty.hidden = false;
  }
};

const renderChart = (canvasId, dataKey, config) => {
  const canvas = document.getElementById(canvasId);
  const chartData = dashboardData[dataKey] || {};
  const values = Array.isArray(chartData.values) ? chartData.values : [];
  if (!canvas) return;
  if (!values.length || values.every((value) => Number(value) === 0)) {
    setChartEmpty(canvas, config.emptyMessage);
    return;
  }
  if (!window.Chart) {
    setChartEmpty(canvas, 'Chart data is unavailable right now.');
    return;
  }

  new Chart(canvas, {
    type: config.type,
    data: {
      labels: chartData.labels || [],
      datasets: [{
        data: values,
        label: config.label,
        borderColor: config.borderColor,
        backgroundColor: config.backgroundColor,
        borderWidth: config.type === 'line' ? 3 : 0,
        fill: config.type === 'line',
        tension: 0.38,
        pointRadius: config.type === 'line' ? 3 : 0,
        pointHoverRadius: 5,
        borderRadius: config.type === 'bar' ? 7 : 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: config.type === 'doughnut' ? '65%' : undefined,
      plugins: {
        legend: {
          display: config.type === 'pie' || config.type === 'doughnut',
          position: 'bottom',
          labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 16, font: { family: 'DM Sans', size: 11 } },
        },
        tooltip: { padding: 10, displayColors: false },
      },
      scales: ['line', 'bar'].includes(config.type) ? {
        x: { grid: { display: false }, ticks: { color: '#756f68', font: { family: 'DM Sans', size: 11 } } },
        y: { beginAtZero: true, grid: { color: '#eee6de' }, ticks: { precision: 0, color: '#756f68', font: { family: 'DM Sans', size: 11 } } },
      } : {},
    },
  });
  canvas.closest('[data-chart-shell]')?.classList.add('is-ready');
};

renderChart('booking-status-chart', 'booking_status', {
  type: 'pie', label: 'Bookings',
  backgroundColor: ['#a95d43', '#5a9a70', '#d49a3a', '#a2403d', '#6d82a5'],
  emptyMessage: 'No booking data to display yet.',
});
renderChart('monthly-bookings-chart', 'monthly_bookings', {
  type: 'line', label: 'Bookings', borderColor: '#a95d43', backgroundColor: 'rgba(169, 93, 67, .14)',
  emptyMessage: 'No monthly bookings to display yet.',
});
renderChart('story-orders-chart', 'story_orders', {
  type: 'bar', label: 'Orders', backgroundColor: '#d49a3a', borderColor: '#d49a3a',
  emptyMessage: 'No Story Shop orders to display yet.',
});
renderChart('approval-progress-chart', 'approval_progress', {
  type: 'doughnut', label: 'Bookings', backgroundColor: ['#5a9a70', '#d49a3a'],
  emptyMessage: 'No approved or pending bookings yet.',
});
