#target photoshop

(function () {
    // Crop, layer duplication and pixel offsets adapted from Group Face Picker.
    function s2t(name) {
        return stringIDToTypeID(name);
    }

    function ActionManager() {
        this.getDescriptor = function (target, id, byIndex) {
            var r = new ActionReference();
            if (id !== undefined && id !== null) {
                if (byIndex) r.putIndex(s2t(target), Number(id));
                else r.putIdentifier(s2t(target), Number(id));
            } else r.putEnumerated(s2t(target), s2t("ordinal"), s2t("targetEnum"));
            return executeActionGet(r);
        };
        this.getProperty = function (target, property) {
            var r = new ActionReference();
            r.putProperty(s2t("property"), s2t(property));
            r.putEnumerated(s2t(target), s2t("ordinal"), s2t("targetEnum"));
            return executeActionGet(r);
        };
        this.documentCount = function () {
            return this.getProperty("application", "numberOfDocuments").getInteger(s2t("numberOfDocuments"));
        };
        this.documentInfo = function (descriptor) {
            var d = descriptor || this.getDescriptor("document");
            var resolution = d.getUnitDoubleValue(s2t("resolution"));
            function pixels(property) {
                var key = s2t(property), value = d.getUnitDoubleValue(key);
                return d.getUnitDoubleType(key) == s2t("pixelsUnit") ? value : value * resolution / 72;
            }
            var width = pixels("width"), height = pixels("height");
            if (!(resolution > 0) || !(width > 0) || !(height > 0) || !isFinite(width) || !isFinite(height)) {
                throw new Error("Не удалось прочитать геометрию документа через AM.");
            }
            var file = d.hasKey(s2t("fileReference")) ? d.getPath(s2t("fileReference")) : null;
            return {id:d.getInteger(s2t("documentID")), width:Math.round(width), height:Math.round(height),
                    file:file, descriptor:d};
        };
        this.findDocument = function (path) {
            var count = this.documentCount();
            for (var i = 1; i <= count; i++) {
                var d = this.getDescriptor("document", i, true);
                if (d.hasKey(s2t("fileReference")) && samePath(d.getPath(s2t("fileReference")).fsName, path)) {
                    return this.documentInfo(d);
                }
            }
            return null;
        };
        this.selectDocument = function (id) {
            var r = new ActionReference(), d = new ActionDescriptor();
            r.putIdentifier(s2t("document"), Number(id));
            d.putReference(s2t("null"), r);
            executeAction(s2t("select"), d, DialogModes.NO);
            return Number(id);
        };
        this.open = function (file) {
            var d = new ActionDescriptor();
            d.putPath(s2t("target"), file);
            d.putBoolean(s2t("forceNotify"), false);
            executeAction(s2t("open"), d, DialogModes.NO);
            return this.documentInfo();
        };
        this.historyID = function () {
            var d = this.getDescriptor("historyState");
            return d.getInteger(s2t("ID"));
        };
        this.restoreHistory = function (id) {
            var r = new ActionReference(), d = new ActionDescriptor();
            r.putIdentifier(s2t("historyState"), Number(id));
            d.putReference(s2t("null"), r);
            executeAction(s2t("select"), d, DialogModes.NO);
        };
        this.crop = function (left, top, right, bottom) {
            var d = new ActionDescriptor(), b = new ActionDescriptor();
            b.putUnitDouble(s2t("left"), s2t("pixelsUnit"), left);
            b.putUnitDouble(s2t("top"), s2t("pixelsUnit"), top);
            b.putUnitDouble(s2t("right"), s2t("pixelsUnit"), right);
            b.putUnitDouble(s2t("bottom"), s2t("pixelsUnit"), bottom);
            d.putObject(s2t("to"), s2t("rectangle"), b);
            d.putUnitDouble(s2t("angle"), s2t("angleUnit"), 0);
            d.putBoolean(s2t("delete"), true);
            d.putEnumerated(s2t("cropAspectRatioModeKey"), s2t("cropAspectRatioModeClass"), s2t("pureAspectRatio"));
            executeAction(s2t("crop"), d, DialogModes.NO);
        };
        this.duplicateLayerTo = function (documentID) {
            var r = new ActionReference(), to = new ActionReference(), d = new ActionDescriptor();
            r.putEnumerated(s2t("layer"), s2t("ordinal"), s2t("targetEnum"));
            to.putIdentifier(s2t("document"), Number(documentID));
            d.putReference(s2t("null"), r);
            d.putReference(s2t("to"), to);
            d.putInteger(s2t("version"), 5);
            var result = executeAction(s2t("duplicate"), d, DialogModes.NO), key = s2t("layerID");
            if (result && result.hasKey(key)) {
                try { return result.getInteger(key); }
                catch (integerIDError) {
                    var ids = result.getList(key);
                    if (ids.count == 1) return ids.getInteger(0);
                }
            }
            // Photoshop activates a layer duplicated into the destination document.
            // Older builds do not return layerID in the action result.
            return null;
        };
        this.selectLayer = function (id) {
            var r = new ActionReference(), d = new ActionDescriptor();
            r.putIdentifier(s2t("layer"), Number(id));
            d.putReference(s2t("null"), r);
            d.putBoolean(s2t("makeVisible"), false);
            executeAction(s2t("select"), d, DialogModes.NO);
        };
        this.layerToFront = function () {
            var r = new ActionReference(), to = new ActionReference(), d = new ActionDescriptor();
            r.putEnumerated(s2t("layer"), s2t("ordinal"), s2t("targetEnum"));
            to.putEnumerated(s2t("layer"), s2t("ordinal"), s2t("front"));
            d.putReference(s2t("null"), r);
            d.putReference(s2t("to"), to);
            d.putBoolean(s2t("adjustment"), false);
            d.putInteger(s2t("version"), 5);
            executeAction(s2t("move"), d, DialogModes.NO);
        };
        this.close = function () {
            var d = new ActionDescriptor();
            d.putEnumerated(s2t("saving"), s2t("yesNo"), s2t("no"));
            executeAction(s2t("close"), d, DialogModes.NO);
        };
    }

    function readLayerBounds() {
        var key = s2t("bounds"), ref = new ActionReference();
        ref.putProperty(s2t("property"), key);
        ref.putEnumerated(s2t("layer"), s2t("ordinal"), s2t("targetEnum"));
        var bounds = executeActionGet(ref).getObjectValue(key);
        return {left:bounds.getUnitDoubleValue(s2t("left")),
                top:bounds.getUnitDoubleValue(s2t("top")),
                right:bounds.getUnitDoubleValue(s2t("right")),
                bottom:bounds.getUnitDoubleValue(s2t("bottom"))};
    }

    function moveLayer(offsetX, offsetY) {
        if (!isFinite(offsetX) || !isFinite(offsetY)) throw new Error("Недопустимое смещение слоя.");
        if (offsetX == 0 && offsetY == 0) return;
        var ref = new ActionReference(), desc = new ActionDescriptor(), offset = new ActionDescriptor();
        ref.putEnumerated(s2t("layer"), s2t("ordinal"), s2t("targetEnum"));
        desc.putReference(s2t("null"), ref);
        offset.putUnitDouble(s2t("horizontal"), s2t("pixelsUnit"), offsetX);
        offset.putUnitDouble(s2t("vertical"), s2t("pixelsUnit"), offsetY);
        desc.putObject(s2t("to"), s2t("offset"), offset);
        executeAction(s2t("move"), desc, DialogModes.NO);
    }

    function renameLayer(name) {
        var ref = new ActionReference(), desc = new ActionDescriptor(), layer = new ActionDescriptor();
        ref.putEnumerated(s2t("layer"), s2t("ordinal"), s2t("targetEnum"));
        desc.putReference(s2t("null"), ref);
        layer.putString(s2t("name"), name);
        desc.putObject(s2t("to"), s2t("layer"), layer);
        executeAction(s2t("set"), desc, DialogModes.NO);
    }

    var am = new ActionManager();

    function samePath(a, b) {
        a = a.replace(/\\/g, "/");
        b = b.replace(/\\/g, "/");
        return /windows/i.test($.os) ? a.toLowerCase() === b.toLowerCase() : a === b;
    }

    function readText(file) {
        file.encoding = "UTF-8";
        if (!file.open("r")) throw new Error("Не удалось открыть " + file.fsName);
        try { return file.read().replace(/^\uFEFF/, ""); }
        finally { file.close(); }
    }

    function integer(value) {
        if (!/^\d+$/.test(value) || Number(value) > 300000) {
            throw new Error("Недопустимое число в face-map.tsv.");
        }
        return Number(value);
    }

    function readJob(target) {
        var folder = target.file.parent, firstJob = null;
        while (folder) {
            var batch = new Folder(folder.absoluteURI + "/_face_retouch");
            var map = new File(batch.absoluteURI + "/face-map.tsv");
            if (map.exists) {
                var job = parseMap(map, batch, folder, target);
                if (job.count) return job;
                if (!firstJob) firstJob = job;
            }
            var parent = folder.parent;
            if (!parent || samePath(parent.fsName, folder.fsName)) break;
            folder = parent;
        }
        if (firstJob) return firstJob;
        throw new Error("Не найден _face_retouch/face-map.tsv в папках выше исходника.");
    }

    function parseMap(map, batch, root, target) {
        var lines = readText(map).split(/\r\n|\n|\r/);
        if (lines[0] !== "FACE_RETOUCH_SHEETS\t1") throw new Error("Неизвестный формат face-map.tsv.");
        var rows = [], sheets = {}, seen = {};
        for (var i = 1; i < lines.length; i++) {
            if (!lines[i]) continue;
            var fields = lines[i].split("\t");
            if (fields.length !== 13) {
                throw new Error("Повреждена строка " + (i + 1) + " в face-map.tsv.");
            }
            var relative = decodeURIComponent(fields[0]);
            var parts = relative.split("/");
            for (var j = 0; j < parts.length; j++) {
                var part = parts[j];
                if (!part || part === "." || part === ".." ||
                        part.indexOf("\\") !== -1 || part.indexOf(":") !== -1) {
                    throw new Error("Недопустимый путь исходника в строке " + (i + 1) + " файла face-map.tsv.");
                }
            }
            var sourcePath = new File(root.absoluteURI + "/" + fields[0]).fsName;
            if (!samePath(sourcePath, target.file.fsName)) continue;

            var sourceW = integer(fields[1]), sourceH = integer(fields[2]);
            var number = integer(fields[3]);
            var left = integer(fields[4]), top = integer(fields[5]);
            var right = integer(fields[6]), bottom = integer(fields[7]);
            var sheetName = fields[8], width = integer(fields[9]), height = integer(fields[10]);
            var x = integer(fields[11]), y = integer(fields[12]);
            if (sourceW !== target.width || sourceH !== target.height) {
                throw new Error("Размер открытого исходника отличается от размера при экспорте.");
            }
            if (!/^faces_\d+\.(jpg|tif|tiff)$/.test(sheetName) || !number || seen[number] ||
                    right <= left || bottom <= top || right > sourceW || bottom > sourceH ||
                    width > 12000 || height > 12000 || x + right - left > width ||
                    y + bottom - top > height) {
                throw new Error("Некорректная геометрия в строке " + (i + 1) + " файла face-map.tsv.");
            }
            var sheet = sheets[sheetName];
            if (!sheet) {
                sheet = sheets[sheetName] = {file: new File(batch.absoluteURI + "/" + sheetName),
                    width: width, height: height, rows: []};
            }
            if (sheet.width !== width || sheet.height !== height) {
                throw new Error("В описании указаны разные размеры " + sheetName + ".");
            }
            var row = {number: number, left: left, top: top,
                width: right - left, height: bottom - top, x: x, y: y};
            seen[number] = true;
            rows.push(row);
            sheet.rows.push(row);
        }
        return {sheets: sheets, count: rows.length};
    }

    function activeLayerID() {
        return am.getProperty("layer", "layerID").getInteger(s2t("layerID"));
    }

    function samePixels(a, b) {
        return Math.abs(a - b) < 0.001;
    }

    function transfer(sheet, target, targetDoc) {
        var donorID = null;
        try {
            var donor = am.open(sheet.file);
            donorID = donor.id;
            if (donor.width !== sheet.width || donor.height !== sheet.height) {
                throw new Error("Размер листа " + sheet.file.name + " изменился.");
            }
            var donorDoc = app.activeDocument;
            if (donorDoc.mode !== DocumentMode.RGB || donorDoc.colorProfileType === ColorProfile.NONE) {
                throw new Error("Лист должен быть RGB с встроенным ICC-профилем. Проверьте настройки цвета Photoshop.");
            }
            var sheetHistory = sheet.rows.length > 1 ? am.historyID() : null;
            for (var i = 0; i < sheet.rows.length; i++) {
                var row = sheet.rows[i];
                am.selectDocument(donorID);
                // Read each rectangle from the full-size sheet.
                if (i > 0) am.restoreHistory(sheetHistory);
                am.crop(row.x, row.y, row.x + row.width, row.y + row.height);
                var crop = am.documentInfo();
                if (crop.width !== row.width || crop.height !== row.height) {
                    throw new Error("Photoshop изменил размер фрагмента при обрезке.");
                }
                if (targetDoc.colorProfileType !== ColorProfile.NONE &&
                        donorDoc.colorProfileName !== targetDoc.colorProfileName) {
                    donorDoc.convertProfile(targetDoc.colorProfileName, Intent.RELATIVECOLORIMETRIC, true, false);
                }
                if (donorDoc.bitsPerChannel !== targetDoc.bitsPerChannel) {
                    donorDoc.bitsPerChannel = targetDoc.bitsPerChannel;
                }
                // Layer via Copy makes a movable pixel layer from the cropped image.
                executeAction(s2t("copyToLayer"), undefined, DialogModes.NO);
                am.selectDocument(target.id);
                var previous = activeLayerID();
                am.selectDocument(donorID);
                var layerID = am.duplicateLayerTo(target.id);
                if (i === sheet.rows.length - 1) {
                    am.selectDocument(donorID);
                    am.close();
                    donorID = null;
                }
                am.selectDocument(target.id);
                if (layerID !== null) am.selectLayer(layerID);
                if (activeLayerID() === previous) throw new Error("Не удалось определить вставленный слой.");
                am.layerToFront();
                var bounds = readLayerBounds();
                if (!samePixels(bounds.right - bounds.left, row.width) ||
                        !samePixels(bounds.bottom - bounds.top, row.height)) {
                    throw new Error("Размер вставленного слоя отличается от размера прямоугольника.");
                }
                moveLayer(row.left - bounds.left, row.top - bounds.top);
                bounds = readLayerBounds();
                if (!samePixels(bounds.left, row.left) || !samePixels(bounds.top, row.top) ||
                        !samePixels(bounds.right, row.left + row.width) ||
                        !samePixels(bounds.bottom, row.top + row.height)) {
                    throw new Error("Не удалось подтвердить координаты вставленного слоя.");
                }
                renameLayer("Ретушь лица " + row.number);
            }
        } finally {
            if (donorID !== null) {
                am.selectDocument(donorID);
                am.close();
            }
            am.selectDocument(target.id);
        }
    }

    function run() {
        if (!am.documentCount()) throw new Error("Откройте исходную фотографию.");
        var target = am.documentInfo(), targetDoc = app.activeDocument;
        if (!target.file) throw new Error("Откройте сохранённый исходный файл.");
        var job = readJob(target), name;
        if (!job.count) return;
        if (targetDoc.mode !== DocumentMode.RGB) throw new Error("Исходник должен быть в режиме RGB.");
        if (targetDoc.bitsPerChannel === BitsPerChannelType.THIRTYTWO) {
            throw new Error("Вставка поддерживает исходники RGB 8 и 16 бит/канал.");
        }
        for (name in job.sheets) {
            if (!job.sheets.hasOwnProperty(name)) continue;
            var file = job.sheets[name].file;
            if (!file.exists) throw new Error("Отсутствует лист " + file.name + ".");
            if (am.findDocument(file.fsName)) throw new Error("Закройте лист " + file.name + " и повторите запуск.");
        }
        var before = targetDoc.activeHistoryState;
        var executionError = null;
        var callback = "__faceRetouchSheetsImport";
        var previousCallback = $.global[callback];
        $.global[callback] = function () {
            try {
                for (var sheet in job.sheets) {
                    if (job.sheets.hasOwnProperty(sheet)) transfer(job.sheets[sheet], target, targetDoc);
                }
            } catch (error) { executionError = error; }
        };
        try {
            targetDoc.suspendHistory("Вставка ретуши лиц", callback + "()");
            if (executionError) throw executionError;
        } catch (error) {
            am.selectDocument(target.id);
            targetDoc.activeHistoryState = before;
            throw error;
        } finally { $.global[callback] = previousCallback; }
    }

    var dialogs = app.displayDialogs;
    try {
        app.displayDialogs = DialogModes.NO;
        run();
    } catch (error) {
        alert("Ретушь лиц\n" + error.message);
    } finally { app.displayDialogs = dialogs; }
}());
