(() => {
  const grid = document.getElementById('booking-calendar-grid');
  if (!grid) return;

  const title = document.getElementById('calendar-title');
  const selectedDateForm = document.getElementById('selected-date-form');
  const selectedDateInput = document.getElementById('selected-booking-date');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let shownMonth = new Date(today.getFullYear(), today.getMonth(), 1);

  const isoDate = (value) => {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, '0');
    const day = String(value.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };
  const monthKey = (value) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}`;

  async function renderCalendar() {
    title.textContent = shownMonth.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
    grid.innerHTML = '<p class="calendar-loading">Checking availability…</p>';
    document.getElementById('previous-month').disabled = shownMonth.getFullYear() === today.getFullYear() && shownMonth.getMonth() === today.getMonth();
    try {
      const response = await fetch(`/api/booking-calendar?month=${monthKey(shownMonth)}`);
      if (!response.ok) throw new Error('Calendar request failed');
      const data = await response.json();
      const statusByDate = Object.fromEntries(data.events.map((event) => [event.date, event.status]));
      drawDays(statusByDate);
    } catch (error) {
      grid.innerHTML = '<p class="calendar-loading">Availability could not be loaded. Please refresh and try again.</p>';
    }
  }

  function drawDays(statusByDate) {
    grid.innerHTML = '';
    const firstWeekday = shownMonth.getDay();
    const daysInMonth = new Date(shownMonth.getFullYear(), shownMonth.getMonth() + 1, 0).getDate();
    for (let blank = 0; blank < firstWeekday; blank += 1) grid.insertAdjacentHTML('beforeend', '<span class="calendar-blank"></span>');
    for (let day = 1; day <= daysInMonth; day += 1) {
      const current = new Date(shownMonth.getFullYear(), shownMonth.getMonth(), day);
      const currentIso = isoDate(current);
      const status = statusByDate[currentIso];
      const past = current < today;
      const unavailable = Boolean(status) || past;
      const stateClass = status ? status.toLowerCase() : 'available';
      const button = document.createElement('button');
      button.type = 'button'; button.className = `calendar-day ${stateClass}${past ? ' past' : ''}`;
      button.textContent = day; button.disabled = unavailable;
      button.title = status ? `${status} booking` : (past ? 'Date has passed' : 'Available');
      if (!unavailable) button.addEventListener('click', () => selectDate(current, button));
      grid.appendChild(button);
    }
  }

  function selectDate(value, button) {
    grid.querySelectorAll('.calendar-day.selected').forEach((day) => day.classList.remove('selected'));
    button.classList.add('selected');
    selectedDateInput.value = isoDate(value);
    selectedDateForm.submit();
  }

  document.getElementById('previous-month').addEventListener('click', () => { shownMonth.setMonth(shownMonth.getMonth() - 1); renderCalendar(); });
  document.getElementById('next-month').addEventListener('click', () => { shownMonth.setMonth(shownMonth.getMonth() + 1); renderCalendar(); });
  renderCalendar();
})();
