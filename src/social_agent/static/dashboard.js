/**
 * Nathan Dashboard — Vanilla JS client.
 *
 * Polls the REST API every REFRESH_INTERVAL seconds.
 * Admin actions require authentication via DASHBOARD_TOKEN.
 *
 * No frameworks. No build tools. Pure fetch + DOM.
 */

"use strict";

var Dashboard = (function () {
    // --- Configuration ---
    var REFRESH_INTERVAL = 5000; // ms
    var MAX_ACTIVITY_ITEMS = 50;

    // --- State ---
    var _token = "";
    var _refreshTimer = null;

    // --- DOM Helpers ---

    function $(id) {
        return document.getElementById(id);
    }

    function setText(id, text) {
        var el = $(id);
        if (el) el.textContent = text;
    }

    function setClass(id, className) {
        var el = $(id);
        if (el) el.className = className;
    }

    function show(id) {
        var el = $(id);
        if (el) el.classList.remove("hidden");
    }

    function hide(id) {
        var el = $(id);
        if (el) el.classList.add("hidden");
    }

    // --- API ---

    function apiGet(endpoint) {
        return fetch("/api/" + endpoint)
            .then(function (r) { return r.json(); })
            .catch(function () { return null; });
    }

    function apiPost(endpoint, body) {
        return fetch("/api/" + endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + _token
            },
            body: JSON.stringify(body || {})
        })
            .then(function (r) { return r.json(); })
            .catch(function () { return null; });
    }

    // --- Formatters ---

    function formatTime(isoString) {
        if (!isoString || isoString === "null") return "\u2014";
        try {
            var d = new Date(isoString);
            return d.toLocaleTimeString();
        } catch (e) {
            return isoString;
        }
    }

    function formatSeconds(seconds) {
        if (seconds == null) return "\u2014";
        if (seconds < 60) return Math.round(seconds) + "s";
        if (seconds < 3600) return Math.round(seconds / 60) + "m";
        return Math.round(seconds / 3600) + "h";
    }

    function healthDotClass(status) {
        switch (status) {
            case "healthy": return "dot dot-healthy";
            case "stuck": return "dot dot-stuck";
            case "dead": return "dot dot-dead";
            default: return "dot dot-unknown";
        }
    }

    // --- Update functions ---

    function updateStatus(data) {
        if (!data) return;

        setText("sandbox-id", data.sandbox_id || "\u2014");

        if (data.health) {
            var h = data.health;
            setClass("health-dot", healthDotClass(h.status));
            setText("health-text", (h.status || "unknown").toUpperCase());
        }

        if (data.state) {
            setText("stat-cycles", data.state.cycle_count || 0);
            setText("stat-posts", data.state.posts_today || 0);
            setText("stat-replies", data.state.replies_today || 0);
        }
    }

    function updateStats(data) {
        if (!data) return;
        setText("stat-actions", data.total_actions || 0);
        setText("stat-success-rate", (data.success_rate || 0) + "%");
        setText("stat-quality", (data.avg_quality || 0).toFixed(2));
    }

    function updateHeartbeat(data) {
        if (!data) return;
        setText("hb-status", (data.status || "unknown").toUpperCase());
        setText("hb-action", data.current_action || "\u2014");
        setText("hb-time", formatTime(data.last_heartbeat));
        setText("hb-seconds", formatSeconds(data.seconds_since_heartbeat));

        // Also update the top status bar from heartbeat
        setClass("health-dot", healthDotClass(data.status));
        setText("health-text", (data.status || "unknown").toUpperCase());
    }

    function updateActivity(data) {
        if (!data || !data.records) return;

        var feed = $("activity-feed");
        if (!feed) return;

        if (data.records.length === 0) {
            feed.innerHTML = '<p class="feed-empty">No activity yet.</p>';
            return;
        }

        var html = "";
        // Show newest first
        var records = data.records.slice().reverse();
        for (var i = 0; i < records.length && i < MAX_ACTIVITY_ITEMS; i++) {
            var r = records[i];
            var successClass = r.success ? "feed-success" : "feed-failure";
            var successText = r.success ? "OK" : "FAIL";
            var quality = r.quality_score ? " (q=" + r.quality_score.toFixed(2) + ")" : "";

            html += '<div class="feed-item">'
                + '<span class="feed-time">' + formatTime(r.timestamp) + '</span>'
                + '<span class="feed-action ' + successClass + '">' + (r.action || "?") + '</span>'
                + '<span class="feed-detail">' + successText + quality + '</span>'
                + '</div>';
        }
        feed.innerHTML = html;
    }

    // --- Refresh loop ---

    function refresh() {
        Promise.all([
            apiGet("status"),
            apiGet("stats"),
            apiGet("heartbeat"),
            apiGet("activity?limit=" + MAX_ACTIVITY_ITEMS)
        ]).then(function (results) {
            updateStatus(results[0]);
            updateStats(results[1]);
            updateHeartbeat(results[2]);
            updateActivity(results[3]);
            setText("last-updated", "Updated: " + new Date().toLocaleTimeString());
        });
    }

    function startRefresh() {
        refresh();
        _refreshTimer = setInterval(refresh, REFRESH_INTERVAL);
    }

    function stopRefresh() {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
    }

    // --- Admin actions ---

    function authenticate() {
        var tokenInput = $("admin-token");
        if (!tokenInput) return;

        _token = tokenInput.value.trim();
        if (!_token) return;

        hide("admin-auth");
        show("admin-controls");
    }

    function showResult(message, isError) {
        var el = $("admin-result");
        if (!el) return;
        el.textContent = message;
        el.className = isError ? "result-error" : "result-success";
        show("admin-result");
        setTimeout(function () { hide("admin-result"); }, 5000);
    }

    function kill() {
        if (!_token) return;
        /* eslint-disable no-restricted-globals */
        if (!confirm("Kill the agent sandbox? This is irreversible.")) return;

        apiPost("kill").then(function (data) {
            if (data && data.killed) {
                showResult("Agent killed. Sandbox: " + data.sandbox_id, false);
            } else {
                showResult("Kill failed: " + JSON.stringify(data), true);
            }
        });
    }

    function injectRule() {
        if (!_token) return;

        var input = $("rule-input");
        if (!input) return;

        var rule = input.value.trim();
        if (!rule) {
            showResult("Rule cannot be empty.", true);
            return;
        }

        apiPost("inject-rule", { rule: rule }).then(function (data) {
            if (data && data.injected) {
                showResult("Rule injected: " + data.rule, false);
                input.value = "";
            } else {
                showResult("Injection failed: " + JSON.stringify(data), true);
            }
        });
    }

    // --- Init ---

    function init() {
        setText("refresh-interval", REFRESH_INTERVAL / 1000);
        startRefresh();
    }

    // Start when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // Public API
    return {
        authenticate: authenticate,
        kill: kill,
        injectRule: injectRule,
        refresh: refresh,
        stopRefresh: stopRefresh
    };
})();
