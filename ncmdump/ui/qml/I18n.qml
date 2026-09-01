pragma Singleton

import QtQuick
import Ncm.App 1.0

QtObject {
    function t(key, values) {
        if (!App || typeof App.translate !== "function")
            return key
        // This read is intentional: it makes every translation binding update
        // immediately after the language changes.
        var revision = App.i18nRevision
        return App.translate(key, values || {})
    }
}
