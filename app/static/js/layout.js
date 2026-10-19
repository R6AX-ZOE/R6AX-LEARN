(function () {
    function ensureOverlay() {
        let overlay = document.getElementById('level-drawer-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'level-drawer-overlay';
            overlay.className = 'level-drawer-overlay';
            overlay.addEventListener('click', closeAllDrawers);
            document.body.appendChild(overlay);
        }
        return overlay;
    }

    function closeAllDrawers() {
        document.querySelectorAll('.level-drawer.open').forEach(function (drawer) {
            drawer.classList.remove('open');
        });
        const overlay = document.getElementById('level-drawer-overlay');
        if (overlay) {
            overlay.classList.remove('show');
        }
        document.body.classList.remove('level-drawer-open');
    }

    window.openLevelDrawer = function (id) {
        const drawer = document.getElementById(id);
        if (!drawer) return;
        closeAllDrawers();
        drawer.classList.add('open');
        ensureOverlay().classList.add('show');
        document.body.classList.add('level-drawer-open');
    };

    window.closeLevelDrawer = function (id) {
        const drawer = document.getElementById(id);
        if (drawer) {
            drawer.classList.remove('open');
        }
        const anyOpen = document.querySelector('.level-drawer.open');
        if (!anyOpen) {
            const overlay = document.getElementById('level-drawer-overlay');
            if (overlay) {
                overlay.classList.remove('show');
            }
            document.body.classList.remove('level-drawer-open');
        }
    };

    window.toggleLevelDrawer = function (id) {
        const drawer = document.getElementById(id);
        if (!drawer) return;
        if (drawer.classList.contains('open')) {
            window.closeLevelDrawer(id);
        } else {
            window.openLevelDrawer(id);
        }
    };

    window.closeAllLevelDrawers = closeAllDrawers;

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeAllDrawers();
        }
    });

    window.addEventListener('resize', function () {
        if (window.innerWidth >= 1024) {
            closeAllDrawers();
        }
    });
})();
