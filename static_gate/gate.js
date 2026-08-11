/**
 * Password-gate overlay behavior, shared by /coddy and /yt-agents.
 *
 * Driven entirely by a `window.__GATE__` config object the server injects
 * (see backend/access.py's inject_gate()) into the page ahead of this script:
 *   { project, label, role, whatsapp, unlockUrl, guestUrl, error, showPasswordForm }
 * `role` is "full" (real page, nothing to do here), "guest" (read-only --
 * banner + fetch lockdown below), or null (locked -- blurred + overlay).
 *
 * The server is the actual security boundary (backend/api/routes.py's
 * require_full()/require_any() 403 mutating/all calls respectively regardless
 * of this script); the fetch() patch below is UX only, so a blocked guest
 * action fails fast with a clear message instead of a raw 403 the app's own
 * error handling has to interpret.
 */
(function () {
    const cfg = window.__GATE__;
    if (!cfg || cfg.role === 'full') return;

    function toast(message) {
        let el = document.getElementById('gate-toast');
        if (!el) {
            el = document.createElement('div');
            el.id = 'gate-toast';
            document.body.appendChild(el);
        }
        el.textContent = message;
        el.classList.add('show');
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => el.classList.remove('show'), 3200);
    }

    // Guests can look, not touch: any non-GET/HEAD call (every mutating
    // endpoint here is POST/DELETE, every read-only one is GET) is short-
    // circuited into a synthetic 403 instead of reaching the network, so the
    // app's existing `if (!response.ok) throw ...` handling shows a failure
    // instead of actually running the action.
    function lockDownFetch() {
        const realFetch = window.fetch.bind(window);
        window.fetch = function (input, init) {
            const method = ((init && init.method) || 'GET').toUpperCase();
            if (method !== 'GET' && method !== 'HEAD') {
                toast('Read-only guest access — enter the password to do this.');
                return Promise.resolve(
                    new Response(
                        JSON.stringify({
                            error: 'Read-only guest access -- enter the password to do this.',
                        }),
                        { status: 403, headers: { 'Content-Type': 'application/json' } },
                    ),
                );
            }
            return realFetch(input, init);
        };
    }

    function showGuestBanner() {
        const bar = document.createElement('div');
        bar.id = 'gate-banner';
        bar.innerHTML =
            '<span>Read-only guest access — sending, building, and deleting are turned off.</span>' +
            '<button type="button" id="gate-banner-request">Request a password</button>' +
            '<button type="button" id="gate-banner-unlock">Enter password</button>';
        document.body.prepend(bar);
        document
            .getElementById('gate-banner-unlock')
            .addEventListener('click', () => showOverlay({ dismissible: true, skipToForm: true }));
        // Already guest, so no need to re-grant it (cfg.guestUrl) here -- just
        // reopen the same WhatsApp chat in case the first message got lost.
        document.getElementById('gate-banner-request').addEventListener('click', () => {
            window.open(cfg.whatsapp, '_blank', 'noopener');
            toast('Opening WhatsApp…');
        });
    }

    function showOverlay(opts) {
        opts = opts || {};
        if (document.getElementById('gate-overlay')) return;

        const errorHtml = cfg.error
            ? '<p class="gate-error">Wrong password — try again.</p>'
            : '';
        const overlay = document.createElement('div');
        overlay.id = 'gate-overlay';
        overlay.className = 'gate-project-' + cfg.project;
        overlay.innerHTML =
            '<div class="gate-card">' +
            (opts.dismissible
                ? '<button type="button" id="gate-close" aria-label="Close" style="position:absolute;top:8px;right:10px;background:none;border:0;font-size:18px;line-height:1;cursor:pointer;color:var(--gate-muted);width:auto;padding:4px;">&times;</button>'
                : '') +
            '<h1>' + cfg.label + '</h1>' +
            '<p class="gate-sub">This project is private.</p>' +
            '<div class="gate-actions" id="gate-actions">' +
            '<button type="button" id="gate-btn-have">I have a password</button>' +
            '<button type="button" id="gate-btn-request">Request a password</button>' +
            '</div>' +
            '<form method="post" action="' + cfg.unlockUrl + '" class="gate-password-form gate-hidden" id="gate-password-form">' +
            '<input type="password" name="password" placeholder="Password" autocomplete="current-password" autofocus required />' +
            '<button type="submit">Enter</button>' +
            '<button type="button" id="gate-btn-back" class="gate-btn-back">Back</button>' +
            errorHtml +
            '</form>' +
            '<p class="gate-note gate-hidden" id="gate-request-note">' +
            'Opening WhatsApp — send the message to request the password. ' +
            "You'll get read-only access to look around in the meantime." +
            '</p>' +
            '</div>';
        document.body.appendChild(overlay);
        document.documentElement.classList.add('gate-locked');

        const actions = overlay.querySelector('#gate-actions');
        const passwordForm = overlay.querySelector('#gate-password-form');
        const requestNote = overlay.querySelector('#gate-request-note');

        function showActions() {
            passwordForm.classList.add('gate-hidden');
            requestNote.classList.add('gate-hidden');
            actions.classList.remove('gate-hidden');
        }

        overlay.querySelector('#gate-btn-have').addEventListener('click', () => {
            actions.classList.add('gate-hidden');
            passwordForm.classList.remove('gate-hidden');
            passwordForm.querySelector('input').focus();
        });

        // Lets someone who clicked "I have a password" by mistake (or changed
        // their mind) get back to the original two-option prompt instead of
        // being stuck on the password field.
        overlay.querySelector('#gate-btn-back').addEventListener('click', showActions);

        overlay.querySelector('#gate-btn-request').addEventListener('click', () => {
            window.open(cfg.whatsapp, '_blank', 'noopener');
            actions.classList.add('gate-hidden');
            requestNote.classList.remove('gate-hidden');
            window.location.href = cfg.guestUrl;
        });

        const closeBtn = overlay.querySelector('#gate-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                overlay.remove();
                document.documentElement.classList.remove('gate-locked');
            });
        }

        if (opts.skipToForm || cfg.showPasswordForm) {
            actions.classList.add('gate-hidden');
            passwordForm.classList.remove('gate-hidden');
        }
    }

    if (cfg.role === 'guest') {
        showGuestBanner();
        lockDownFetch();
        // A guest who tried to upgrade via the banner's "Enter password" but
        // typed it wrong still needs to see that -- reopen the overlay
        // straight to the password form (with the error message) instead of
        // silently dropping back to just the banner.
        if (cfg.error) {
            showOverlay({ dismissible: true, skipToForm: true });
        }
        return;
    }

    // Locked (no session at all). Dismissible -- the blur/lockout comes back
    // on the next reload regardless, so closing this is harmless, just a way
    // to peek at the page underneath without committing to either option.
    showOverlay({ dismissible: true });
})();
