'use strict';

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------
let state = null;
let sessionId = null;
let selectedDiscard = null;

const SUIT_SYMBOLS = { S: '♠', C: '♣', H: '♥', D: '♦' };
const SEAT_SLOTS = { 1: 'west', 2: 'north', 3: 'east' };
const TRICK_SLOTS = { 0: 'south', 1: 'west', 2: 'north', 3: 'east' };

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', init);

async function init() {
  const savedId = localStorage.getItem('euchre_session_id');
  if (savedId) {
    try {
      const res = await fetch(`/api/state/${savedId}`);
      if (res.ok) {
        state = await res.json();
        sessionId = savedId;
        render(state);
        return;
      }
    } catch (_) {}
  }
  await startNewGame();
}

async function startNewGame() {
  const res = await fetch('/api/new-game', { method: 'POST' });
  state = await res.json();
  sessionId = state.session_id;
  localStorage.setItem('euchre_session_id', sessionId);
  render(state);
}

async function sendAction(action) {
  try {
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, action }),
    });
    state = await res.json();
    if (state.error) showError(state.error);
    render(state);
  } catch (err) {
    showError('Network error — is the server running?');
  }
}

// ---------------------------------------------------------------------------
// Main render dispatcher
// ---------------------------------------------------------------------------
function render(s) {
  renderScoreboard(s);
  renderSidebar(s);
  renderOpponentSeats(s);
  renderTrickArea(s);
  renderGoingAloneNotice(s);
  renderSouthHand(s);
  renderActionPanel(s);
  renderLog(s);
}

function renderGoingAloneNotice(s) {
  const div = document.getElementById('going-alone-notice');
  if (!s.going_alone || s.trump_caller === 0) {
    div.innerHTML = '';
    div.className = '';
    return;
  }
  const PARTNER_SEAT = 2;
  if (s.trump_caller === PARTNER_SEAT) {
    div.className = 'going-alone-notice notice-partner';
    div.innerHTML = '⚠ Your partner (North) is going alone — you are sitting out this hand.';
  } else {
    const callerName = s.opponent_hands[String(s.trump_caller)]?.name ?? 'Opponent';
    const sittingOutSeat = (s.trump_caller + 2) % 4;
    const sittingOutName = sittingOutSeat === 0
      ? 'You'
      : (s.opponent_hands[String(sittingOutSeat)]?.name ?? 'Unknown');
    div.className = 'going-alone-notice notice-opponent';
    div.innerHTML = `${callerName} is going alone — ${sittingOutName} is sitting out.`;
  }
}

// ---------------------------------------------------------------------------
// Scoreboard
// ---------------------------------------------------------------------------
function renderScoreboard(s) {
  const [t0, t1] = s.team_names;
  const [p0, p1] = s.scores;

  document.getElementById('score-team0').innerHTML = `
    <div class="score-team-name">${t0}</div>
    <div class="score-points">${p0} ${pips(p0)}</div>
  `;
  document.getElementById('score-team1').innerHTML = `
    <div class="score-team-name">${t1}</div>
    <div class="score-points">${p1} ${pips(p1)}</div>
  `;

  const trumpEl = document.getElementById('trump-display');
  if (s.trump) {
    const sym = SUIT_SYMBOLS[s.trump];
    const isRed = s.trump === 'H' || s.trump === 'D';
    trumpEl.innerHTML = `
      <div style="font-size:11px;color:#94a3b8">Trump</div>
      <div class="trump-suit ${isRed ? 'red' : 'black'}">${sym}</div>
      <div style="font-size:10px;color:#64748b">${s.dealer_name} dealt</div>
    `;
  } else {
    trumpEl.innerHTML = `<div style="font-size:11px;color:#64748b">Bidding…</div>`;
  }
}

function pips(n) {
  const total = 10;
  let html = '<span class="score-pips">';
  for (let i = 0; i < Math.min(n, total); i++) html += '<span class="score-pip"></span>';
  for (let i = n; i < total; i++) html += '<span class="score-pip empty"></span>';
  return html + '</span>';
}

// ---------------------------------------------------------------------------
// Opponent seats (N, W, E)
// ---------------------------------------------------------------------------
function renderOpponentSeats(s) {
  [1, 2, 3].forEach(seat => {
    const info = s.opponent_hands[String(seat)];
    const slotName = SEAT_SLOTS[seat];
    const cardsEl = document.getElementById(`${slotName}-cards`);
    const seatEl = document.getElementById(`seat-${slotName}`);

    // Sitting out
    if (!info.is_active) {
      seatEl.classList.add('sitting-out');
      cardsEl.innerHTML = '<span class="sitting-out-label">SITTING OUT</span>';
      return;
    }
    seatEl.classList.remove('sitting-out');

    // Dealer badge
    const seatDiv = seatEl;
    let badge = seatDiv.querySelector('.dealer-btn');
    if (seat === s.dealer) {
      if (!badge) {
        badge = document.createElement('div');
        badge.className = 'dealer-btn';
        badge.textContent = 'D';
        seatDiv.appendChild(badge);
      }
    } else if (badge) {
      badge.remove();
    }

    cardsEl.innerHTML = '';
    for (let i = 0; i < info.card_count; i++) {
      cardsEl.appendChild(buildCardBack());
    }
  });
}

// ---------------------------------------------------------------------------
// Trick area / upcard
// ---------------------------------------------------------------------------
function renderTrickArea(s) {
  // Clear all slots
  ['north', 'south', 'east', 'west'].forEach(pos => {
    document.getElementById(`trick-${pos}`).innerHTML = '';
  });
  const center = document.getElementById('trick-center');

  // Show upcard during bidding
  if (s.upcard && (s.phase === 'BIDDING_R1' || s.phase === 'BIDDING_R2')) {
    const container = document.createElement('div');
    container.className = 'upcard-container' + (s.phase === 'BIDDING_R2' ? ' turned-down' : '');
    const lbl = document.createElement('div');
    lbl.className = 'upcard-label';
    lbl.textContent = s.phase === 'BIDDING_R2' ? 'Turned Down' : 'Upcard';
    container.appendChild(lbl);
    container.appendChild(buildCard(s.upcard));
    document.getElementById('trick-north').appendChild(container);
    center.textContent = s.phase === 'BIDDING_R1' ? 'Round 1' : 'Round 2';
    return;
  }

  // Show trick plays
  if (s.current_trick && s.current_trick.length > 0) {
    s.current_trick.forEach(play => {
      const pos = TRICK_SLOTS[play.seat];
      const slot = document.getElementById(`trick-${pos}`);
      const nameEl = document.createElement('div');
      nameEl.className = 'trick-player-name';
      nameEl.textContent = play.seat_name;
      slot.appendChild(nameEl);
      const cardEl = buildCard(play.card, { trump: s.trump });
      if (s.phase === 'TRICK_COMPLETE' && play.seat === s.trick_winner_seat) {
        cardEl.classList.add('trick-winner');
      }
      slot.appendChild(cardEl);
    });
    if (s.trick_num !== null) {
      center.textContent = `Trick ${s.trick_num + 1}`;
    }
  } else if (s.phase === 'PLAYING_TRICK') {
    center.textContent = s.trick_num !== null ? `Trick ${s.trick_num + 1}` : '';
  } else {
    center.textContent = '';
  }
}

// ---------------------------------------------------------------------------
// Human hand (South)
// ---------------------------------------------------------------------------
function renderSouthHand(s) {
  const el = document.getElementById('south-cards');
  el.innerHTML = '';
  selectedDiscard = null;

  // Dealer badge on south seat
  const southSeat = document.getElementById('seat-south');
  let badge = southSeat.querySelector('.dealer-btn');
  if (s.dealer === 0) {
    if (!badge) {
      badge = document.createElement('div');
      badge.className = 'dealer-btn';
      badge.textContent = 'D';
      southSeat.appendChild(badge);
    }
  } else if (badge) {
    badge.remove();
  }

  const legalIds = new Set(s.legal_ids || []);
  const isPlaying = s.phase === 'PLAYING_TRICK';
  const isDiscarding = s.phase === 'DISCARDING';

  s.your_hand.forEach(card => {
    const isLegal = legalIds.has(card.id);
    const isTrump = s.trump && card.suit === s.trump ||
      (s.trump && card.rank === 'J' && isSameColor(card.suit, s.trump));
    const cardEl = buildCard(card, { trump: s.trump, isTrump });

    if (isPlaying && isLegal) {
      cardEl.classList.add('legal');
      cardEl.addEventListener('click', () => sendAction({ type: 'PLAY_CARD', card_id: card.id }));
    } else if (isPlaying && !isLegal) {
      cardEl.classList.add('inactive');
    } else if (isDiscarding) {
      cardEl.classList.add('selectable');
      cardEl.addEventListener('click', () => toggleDiscard(cardEl, card.id, el));
    } else {
      cardEl.classList.add('inactive');
    }

    el.appendChild(cardEl);
  });
}

function isSameColor(suit1, suit2) {
  const red = new Set(['H', 'D']);
  const black = new Set(['S', 'C']);
  return (red.has(suit1) && red.has(suit2)) || (black.has(suit1) && black.has(suit2));
}

function toggleDiscard(cardEl, cardId, container) {
  const prev = container.querySelector('.selected-discard');
  if (prev && prev !== cardEl) prev.classList.remove('selected-discard');
  cardEl.classList.toggle('selected-discard');
  selectedDiscard = cardEl.classList.contains('selected-discard') ? cardId : null;
  // Update confirm button state
  const btn = document.getElementById('confirm-discard-btn');
  if (btn) btn.disabled = !selectedDiscard;
}

// ---------------------------------------------------------------------------
// Action panel (phase-specific)
// ---------------------------------------------------------------------------
function renderActionPanel(s) {
  const panel = document.getElementById('action-panel');
  panel.innerHTML = '';

  switch (s.phase) {
    case 'BIDDING_R1':    return renderBidR1Panel(panel, s);
    case 'BIDDING_R2':    return renderBidR2Panel(panel, s);
    case 'DISCARDING':    return renderDiscardPanel(panel, s);
    case 'PLAYING_TRICK': return renderPlayingPanel(panel, s);
    case 'TRICK_COMPLETE':return renderTrickCompletePanel(panel, s);
    case 'HAND_COMPLETE': return renderHandCompletePanel(panel, s);
    case 'GAME_OVER':     return renderGameOverPanel(panel, s);
  }
}

function renderBidR1Panel(panel, s) {
  const title = el('div', 'action-title', `Round 1 — Order up ${s.upcard ? s.upcard.display : ''}?`);
  panel.appendChild(title);

  const aloneRow = el('label', 'alone-row');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.id = 'alone-check';
  aloneRow.appendChild(checkbox);
  aloneRow.appendChild(document.createTextNode(' Go alone?'));

  const row = el('div', 'action-row');

  const orderBtn = btn('Order Up', 'btn-primary', () => {
    sendAction({ type: 'BID_R1', choice: 'order', alone: checkbox.checked });
  });
  const passBtn = btn('Pass', 'btn-secondary', () => {
    sendAction({ type: 'BID_R1', choice: 'pass', alone: false });
  });

  // Show upcard mini preview
  if (s.upcard) {
    const preview = el('div', 'upcard-preview');
    preview.appendChild(buildCard(s.upcard));
    row.appendChild(preview);
  }
  row.appendChild(orderBtn);
  row.appendChild(passBtn);

  panel.appendChild(row);
  panel.appendChild(aloneRow);

  if (s.hint) {
    const hintRow = el('div', 'action-row');
    const hintBtn = btn('💡 Show Hint', 'btn-secondary', () => toggleHint(panel, s.hint));
    hintBtn.id = 'hint-toggle-btn';
    hintRow.appendChild(hintBtn);
    panel.appendChild(hintRow);
  }
}

function renderBidR2Panel(panel, s) {
  const title = el('div', 'action-title', `Round 2 — Name a suit`);
  panel.appendChild(title);

  const aloneRow = el('label', 'alone-row');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.id = 'alone-check';
  aloneRow.appendChild(checkbox);
  aloneRow.appendChild(document.createTextNode(' Go alone?'));

  const row = el('div', 'action-row');

  const suits = ['S', 'C', 'H', 'D'];
  suits.forEach(suit => {
    const isExcluded = suit === s.excluded_suit;
    const isRed = suit === 'H' || suit === 'D';
    const suitBtn = btn(SUIT_SYMBOLS[suit], `btn-suit${isRed ? ' red' : ''}`, () => {
      sendAction({ type: 'BID_R2', choice: suit, alone: checkbox.checked });
    });
    suitBtn.disabled = isExcluded;
    suitBtn.title = isExcluded ? 'This suit was turned down' : '';
    row.appendChild(suitBtn);
  });

  const canPass = s.can_pass_r2;
  const passBtn = btn('Pass', 'btn-secondary', () => {
    sendAction({ type: 'BID_R2', choice: 'pass', alone: false });
  });
  passBtn.disabled = !canPass;
  if (!canPass) passBtn.title = 'Stick the dealer — you must call a suit';
  row.appendChild(passBtn);

  panel.appendChild(row);
  panel.appendChild(aloneRow);

  if (s.hint) {
    const hintRow = el('div', 'action-row');
    const hintBtn = btn('💡 Show Hint', 'btn-secondary', () => toggleHint(panel, s.hint));
    hintBtn.id = 'hint-toggle-btn';
    hintRow.appendChild(hintBtn);
    panel.appendChild(hintRow);
  }
}

function renderDiscardPanel(panel, s) {
  const title = el('div', 'action-title', 'You picked up the upcard — click a card in your hand to discard');
  panel.appendChild(title);

  const row = el('div', 'action-row');
  const confirmBtn = btn('Confirm Discard', 'btn-danger', () => {
    if (selectedDiscard) sendAction({ type: 'DISCARD', card_id: selectedDiscard });
  });
  confirmBtn.id = 'confirm-discard-btn';
  confirmBtn.disabled = true;
  row.appendChild(confirmBtn);
  panel.appendChild(row);
}

function renderPlayingPanel(panel, s) {
  const title = el('div', 'action-title', 'Your turn — click a highlighted card to play');
  panel.appendChild(title);

  const row = el('div', 'action-row');
  const info = el('div', '', `Tricks: ${s.trick_counts[0]}–${s.trick_counts[1]}`);
  info.style.cssText = 'font-size:13px;color:#94a3b8';
  row.appendChild(info);

  if (s.hint) {
    const hintBtn = btn('💡 Show Hint', 'btn-secondary', () => toggleHint(panel, s.hint));
    hintBtn.id = 'hint-toggle-btn';
    row.appendChild(hintBtn);
  }

  panel.appendChild(row);
}

function toggleHint(panel, hint) {
  let box = panel.querySelector('.hint-box');
  const hintBtn = panel.querySelector('#hint-toggle-btn');
  if (box) {
    box.remove();
    if (hintBtn) hintBtn.textContent = '💡 Show Hint';
  } else {
    box = el('div', 'hint-box');
    if (hint.type === 'bid') {
      const actionDisplay = el('div', 'hint-card-display', hint.display);
      box.appendChild(actionDisplay);
    } else {
      const isRed = hint.card.is_red;
      const cardDisplay = el('div', `hint-card-display ${isRed ? 'red' : 'black'}`,
        hint.display);
      box.appendChild(cardDisplay);
    }
    const explain = el('div', 'hint-explanation', '');
    hint.explanation.split('\n').forEach((line, i) => {
      if (i > 0) explain.appendChild(document.createElement('br'));
      explain.appendChild(document.createTextNode(line));
    });
    box.appendChild(explain);
    panel.appendChild(box);
    if (hintBtn) hintBtn.textContent = '💡 Hide Hint';
  }
}

function renderTrickCompletePanel(panel, s) {
  const lt = s.last_trick;
  if (!lt) return;

  const box = el('div', 'trick-explanation');
  box.appendChild(el('div', 'winner-label', `${lt.winner_name} wins the trick`));
  box.appendChild(el('div', '', lt.explanation));
  panel.appendChild(box);

  const row = el('div', 'action-row');
  row.appendChild(btn('Next Trick →', 'btn-primary', () => {
    sendAction({ type: 'NEXT_TRICK' });
  }));
  panel.appendChild(row);
}

function renderHandCompletePanel(panel, s) {
  const yourTricks = s.trick_counts[0];
  const oppTricks  = s.trick_counts[1];
  const won = s.point_delta[0] > 0;
  const pts = won ? s.point_delta[0] : s.point_delta[1];

  const summary = el('div', 'hand-summary');
  const label = el('div', `result-label${won ? '' : ' loss'}`,
    won ? `+${pts} point${pts > 1 ? 's' : ''}!` : `Opponents score ${pts}`);
  const sub = el('div', 'sub-label', `Tricks: You ${yourTricks} – Opp ${oppTricks}`);
  summary.appendChild(label);
  summary.appendChild(sub);
  panel.appendChild(summary);

  const row = el('div', 'action-row');

  if (!s.grade_report) {
    const gradeBtn = btn('View Grade Report', 'btn-secondary', () => {
      sendAction({ type: 'REQUEST_GRADE' });
    });
    row.appendChild(gradeBtn);
  }

  const nextBtn = btn('Next Hand →', 'btn-primary', () => {
    sendAction({ type: 'NEXT_HAND' });
  });
  row.appendChild(nextBtn);
  panel.appendChild(row);

  if (s.grade_report) {
    panel.appendChild(renderGradeReport(s.grade_report));
  }
}

function renderGradeReport(report) {
  const container = el('div', 'grade-report');
  container.appendChild(el('div', 'grade-summary', report.summary));

  if (report.hand_scores && Object.keys(report.hand_scores).length > 0) {
    container.appendChild(el('div', 'grade-section-title', 'Hand Strengths'));
    const scoreRow = el('div', 'hand-score-row');
    [0, 1, 2, 3].forEach(seat => {
      const entry = report.hand_scores[String(seat)];
      if (!entry) return;
      const cell = el('div', 'hand-score-cell');
      cell.appendChild(el('div', 'hand-score-name', entry.name));
      cell.appendChild(el('div', 'hand-score-value', entry.score.toFixed(1)));
      scoreRow.appendChild(cell);
    });
    container.appendChild(scoreRow);
  }

  if (report.bid_grades.length > 0) {
    container.appendChild(el('div', 'grade-section-title', 'Bidding'));
    report.bid_grades.forEach(g => {
      const item = el('div', 'grade-item');
      const row = el('div', 'grade-row');
      row.appendChild(el('span', `grade-verdict ${g.verdict}`, g.verdict));
      row.appendChild(el('span', '', `Rd${g.round}: You ${g.your_choice}${g.your_alone ? ' alone' : ''}`));
      if (g.verdict !== 'OPTIMAL') {
        row.appendChild(el('span', 'grade-ai', `→ AI: ${g.ai_action}${g.ai_alone ? ' alone' : ''}`));
      }
      item.appendChild(row);
      item.appendChild(el('div', 'grade-explanation', g.explanation));
      container.appendChild(item);
    });
  }

  if (report.play_grades.length > 0) {
    container.appendChild(el('div', 'grade-section-title', 'Card Play'));
    report.play_grades.forEach(g => {
      const item = el('div', 'grade-item');
      const row = el('div', 'grade-row');
      row.appendChild(el('span', `grade-verdict ${g.verdict}`, g.verdict));
      row.appendChild(el('span', '', `Trick ${g.trick_num}: You played ${g.your_card.display}`));
      if (g.verdict !== 'OPTIMAL') {
        row.appendChild(el('span', 'grade-ai', `→ AI: ${g.ai_card.display}`));
      }
      item.appendChild(row);
      item.appendChild(el('div', 'grade-explanation', g.explanation));
      if (g.counterfactual) {
        const cfDiv = el('div', 'grade-counterfactual');
        g.counterfactual.split('\n').forEach((line, i) => {
          if (i > 0) cfDiv.appendChild(document.createElement('br'));
          cfDiv.appendChild(document.createTextNode(line));
        });
        item.appendChild(cfDiv);
      }
      container.appendChild(item);
    });
  }

  if (report.narrative) {
    const narrative = el('div', '');
    narrative.style.cssText = 'margin-top:10px;padding:8px 10px;background:#0f3460;border-radius:6px;font-size:12px;color:#cbd5e1;line-height:1.5;';
    narrative.textContent = report.narrative;
    container.appendChild(narrative);
  }

  return container;
}

function renderGameOverPanel(panel, s) {
  const won = s.scores[0] >= 10;
  const msg = el('div', 'game-over-msg');
  msg.appendChild(el('h2', won ? '' : 'loss', won ? '🏆 You win!' : 'Opponents win'));
  msg.appendChild(el('p', '', `Final: ${s.scores[0]}–${s.scores[1]}`));
  panel.appendChild(msg);

  const row = el('div', 'action-row');
  row.appendChild(btn('Play Again', 'btn-primary', () => {
    sendAction({ type: 'NEW_GAME' });
  }));
  panel.appendChild(row);
}

// ---------------------------------------------------------------------------
// Log panel
// ---------------------------------------------------------------------------
function renderLog(s) {
  const entries = document.getElementById('log-entries');
  if (s.action_log && s.action_log.length > 0) {
    entries.innerHTML = s.action_log.map(msg => `<span>${msg}</span>`).join('');
  }
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
function renderSidebar(s) {
  renderSidebarTrump(s);
  renderSidebarTricks(s);
}

function renderSidebarTrump(s) {
  const el2 = document.getElementById('sidebar-trump');
  if (!s.trump) {
    el2.innerHTML = `
      <div class="sidebar-trump-label">Trump</div>
      <div style="font-size:13px;color:#4a5568;margin-top:4px">Bidding…</div>
    `;
    return;
  }
  const sym = SUIT_SYMBOLS[s.trump];
  const isRed = s.trump === 'H' || s.trump === 'D';
  const callerName = s.trump_caller === 0 ? 'You' :
    (s.opponent_hands[String(s.trump_caller)]?.name ?? '?');
  el2.innerHTML = `
    <div class="sidebar-trump-label">Trump</div>
    <div class="sidebar-trump-suit ${isRed ? 'red' : 'black'}">${sym}</div>
    <div class="sidebar-trump-caller">Called by ${callerName}</div>
  `;
}

function renderSidebarTricks(s) {
  const container = document.getElementById('sidebar-tricks');
  container.innerHTML = '';

  const tricks = s.completed_tricks || [];
  const handLog = s.hand_log || [];

  // Hand event log (bidding + early events)
  const logDiv = el('div', '');
  logDiv.appendChild(el('div', 'sidebar-section-title', 'This Hand'));
  const logEntries = el('div', 'sidebar-hand-log');

  // Show bidding events (everything before trump was set)
  const biddingEvents = handLog.filter(msg =>
    msg.includes('passes') || msg.includes('orders up') ||
    msg.includes('calls') || msg.includes('Dealer') ||
    msg.includes('Trump:') || msg.includes('named') ||
    msg.includes('Dealer') || msg.includes('Hand ')
  );
  biddingEvents.forEach(msg => {
    const isTrump = msg.includes('Trump:') || msg.includes('orders up') || msg.includes('calls');
    logEntries.appendChild(el('div', `sidebar-log-entry${isTrump ? ' highlight' : ''}`, msg));
  });
  logDiv.appendChild(logEntries);
  container.appendChild(logDiv);

  if (tricks.length === 0) return;

  // Trick history
  const tricksDiv = el('div', '');
  tricksDiv.appendChild(el('div', 'sidebar-section-title', 'Tricks'));

  tricks.forEach(trick => {
    const trickEl = el('div', 'sidebar-trick');

    const header = el('div', 'sidebar-trick-header');
    header.appendChild(el('span', 'sidebar-trick-num', `Trick ${trick.trick_num + 1}`));
    header.appendChild(el('span', 'sidebar-trick-winner', `${trick.winner_name} wins`));
    trickEl.appendChild(header);

    const plays = el('div', 'sidebar-trick-plays');
    trick.plays.forEach(play => {
      const isWinner = play.seat === trick.winner_seat;
      const row = el('div', `sidebar-play${isWinner ? ' winner' : ''}`);
      row.appendChild(el('span', '', play.seat_name));
      const isRed = play.card.is_red;
      row.appendChild(el('span', `sidebar-play-card ${isRed ? 'red' : 'black'}`,
        play.card.display + (isWinner ? ' ★' : '')));
      plays.appendChild(row);
    });
    trickEl.appendChild(plays);

    const why = el('div', 'sidebar-trick-why', trick.explanation);
    trickEl.appendChild(why);
    tricksDiv.appendChild(trickEl);
  });

  container.appendChild(tricksDiv);
}

// ---------------------------------------------------------------------------
// Card builder
// ---------------------------------------------------------------------------
function buildCard(card, { trump = null, isTrump = false } = {}) {
  const cardEl = document.createElement('div');
  const isRed = card.is_red;
  cardEl.className = `card ${isRed ? 'red' : 'black'}`;
  cardEl.dataset.cardId = card.id;

  const sym = SUIT_SYMBOLS[card.suit];

  // Detect trump (server tells us trump suit; left bower check)
  if (trump && (card.suit === trump || (card.rank === 'J' && isSameColor(card.suit, trump)))) {
    cardEl.classList.add('is-trump');
  }

  cardEl.innerHTML = `
    <span class="card-corner top">
      <span class="card-rank">${card.rank}</span>
      <span class="card-suit">${sym}</span>
    </span>
    <span class="card-center">${sym}</span>
    <span class="card-corner bottom">
      <span class="card-rank">${card.rank}</span>
      <span class="card-suit">${sym}</span>
    </span>
  `;
  return cardEl;
}

function buildCardBack() {
  const el = document.createElement('div');
  el.className = 'card-back';
  return el;
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------
function el(tag, className, text = '') {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text) e.textContent = text;
  return e;
}

function btn(text, className, onClick) {
  const b = document.createElement('button');
  b.className = `btn ${className}`;
  b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

function showError(msg) {
  let toast = document.getElementById('error-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'error-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.display = 'block';
  setTimeout(() => { toast.style.display = 'none'; }, 3000);
}
