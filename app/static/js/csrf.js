(function () {
    function getCookie(name) {
        var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
        return m ? decodeURIComponent(m[1]) : null;
    }

    var UNSAFE = ['POST', 'PUT', 'PATCH', 'DELETE'];

    function csrfToken() {
        return getCookie('csrf_token') || '';
    }

    function decorate(options) {
        options = options || {};
        if (UNSAFE.indexOf((options.method || 'GET').toUpperCase()) === -1) {
            return options;
        }
        var headers = new Headers(options.headers || {});
        if (!headers.has('X-CSRF-Token')) {
            headers.set('X-CSRF-Token', csrfToken());
        }
        options.headers = headers;
        return options;
    }

    var originalFetch = window.fetch;
    window.fetch = function (input, options) {
        return originalFetch.call(this, input, decorate(options));
    };

    document.addEventListener('htmx:configRequest', function (e) {
        var method = (e.detail.verb || 'get').toUpperCase();
        if (UNSAFE.indexOf(method) !== -1) {
            e.detail.headers['X-CSRF-Token'] = csrfToken();
        }
    });
})();
