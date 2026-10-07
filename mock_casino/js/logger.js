// Sendet Ereignisse an den lokalen Server (POST /api/log).
// Der Server schreibt sie nur im Debug-Modus in die Ground-Truth-Datei.

export class GroundTruthLogger {
  constructor(enabled) {
    this.enabled = enabled;
    // Ereignisse nacheinander senden, damit die Reihenfolge in der Datei stimmt
    this.queue = Promise.resolve();
  }

  log(type, data = {}) {
    if (!this.enabled) return;
    const event = { type, client_time: new Date().toISOString(), ...data };
    this.queue = this.queue
      .then(() =>
        fetch('/api/log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(event),
        }),
      )
      .catch((err) => console.warn('Ground-Truth-Log fehlgeschlagen:', err));
  }

  // Wartet, bis alle Ereignisse gesendet wurden (für Tests)
  flush() {
    return this.queue;
  }
}
