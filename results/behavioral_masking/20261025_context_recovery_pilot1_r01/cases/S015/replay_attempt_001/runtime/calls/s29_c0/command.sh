cd /app && python - <<'PY'
path = 'bandit/core/manager.py'
src = open(path).read()

old = '''    def run_tests(self):
        """Runs through all files in the scope

        :return: -
        """
        # if we have problems with a file, we'll remove it from the files_list
        # and add it to the skipped list instead
        new_files_list = list(self.files_list)
        if (
            len(self.files_list) > PROGRESS_THRESHOLD
            and LOG.getEffectiveLevel() <= logging.INFO
        ):
            files = progress.track(self.files_list)
        else:
            files = self.files_list

        for count, fname in enumerate(files):
            LOG.debug("working on file : %s", fname)

            try:
                if fname == "-":
                    open_fd = os.fdopen(sys.stdin.fileno(), "rb", 0)
                    fdata = io.BytesIO(open_fd.read())
                    new_files_list = [
                        "<stdin>" if x == "-" else x for x in new_files_list
                    ]
                    self._parse_file("<stdin>", fdata, new_files_list)
                else:
                    with open(fname, "rb") as fdata:
                        self._parse_file(fname, fdata, new_files_list)
            except OSError as e:
                self.skipped.append((fname, e.strerror))
                new_files_list.remove(fname)

        # reflect any files which may have been skipped
        self.files_list = new_files_list

        # do final aggregation of metrics
        self.metrics.aggregate()
'''

new = '''    def run_tests(self, cache=None, force_rescan=False):
        """Runs through all files in the scope

        :param cache: Optional :class:`BanditCache` used for incremental
            analysis
        :param force_rescan: If True, bypass cache lookups but still store
            results
        :return: -
        """
        self.cache = cache
        self.cache_total_files = len(self.files_list)

        cached_scores = {}
        scan_scores = {}
        scan_cache_data = {}

        files_to_scan = self.files_list
        if cache is not None:
            files_to_scan, cached_scores = self._prepare_cache(
                cache, force_rescan
            )

        # if we have problems with a file, we'll remove it from the files_list
        # and add it to the skipped list instead
        new_files_list = list(self.files_list)
        if (
            len(files_to_scan) > PROGRESS_THRESHOLD
            and LOG.getEffectiveLevel() <= logging.INFO
        ):
            files = progress.track(files_to_scan)
        else:
            files = files_to_scan

        for count, fname in enumerate(files):
            LOG.debug("working on file : %s", fname)
            self.files_scanned.append(fname)

            try:
                if fname == "-":
                    open_fd = os.fdopen(sys.stdin.fileno(), "rb", 0)
                    fdata = io.BytesIO(open_fd.read())
                    new_files_list = [
                        "<stdin>" if x == "-" else x for x in new_files_list
                    ]
                    self._parse_file(
                        "<stdin>",
                        fdata,
                        new_files_list,
                        scan_scores,
                        scan_cache_data,
                    )
                else:
                    with open(fname, "rb") as fdata:
                        self._parse_file(
                            fname,
                            fdata,
                            new_files_list,
                            scan_scores,
                            scan_cache_data,
                        )
            except OSError as e:
                self.skipped.append((fname, e.strerror))
                new_files_list.remove(fname)

        # reflect any files which may have been skipped
        self.files_list = new_files_list

        if cache is not None:
            self._store_cache_entries(cache, scan_cache_data)
            cache.save()

        # Build scores in files_list order so verbose output stays aligned.
        self.scores = []
        for fname in self.files_list:
            if fname in cached_scores:
                self.scores.append(cached_scores[fname])
            elif fname in scan_scores:
                self.scores.append(scan_scores[fname])
            else:
                self.scores.append(self._empty_score())

        self.metrics.data["_totals"]["cache_hits"] = self.cache_hits
        self.metrics.data["_totals"]["cache_misses"] = self.cache_misses

        # do final aggregation of metrics
        self.metrics.aggregate()
'''

assert old in src, "run_tests block not found"
src = src.replace(old, new, 1)

# Replace _parse_file
old2 = '''    def _parse_file(self, fname, fdata, new_files_list):
        try:
            # parse the current file
            data = fdata.read()
            lines = data.splitlines()
            self.metrics.begin(fname)
            self.metrics.count_locs(lines)
            # nosec_lines is a dict of line number -> set of tests to ignore
            #                                         for the line
            nosec_lines = dict()
            try:
                fdata.seek(0)
                tokens = tokenize.tokenize(fdata.readline)

                if not self.ignore_nosec:
                    for toktype, tokval, (lineno, _), _, _ in tokens:
                        if toktype == tokenize.COMMENT:
                            nosec_lines[lineno] = _parse_nosec_comment(tokval)

            except tokenize.TokenError:
                pass
            score = self._execute_ast_visitor(fname, fdata, data, nosec_lines)
            self.scores.append(score)
            self.metrics.count_issues([score])
        except KeyboardInterrupt:
            sys.exit(2)
        except SyntaxError:
            self.skipped.append(
                (fname, "syntax error while parsing AST from file")
            )
            new_files_list.remove(fname)
        except Exception as e:
            LOG.error(
                "Exception occurred when executing tests against %s.", fname
            )
            if not LOG.isEnabledFor(logging.DEBUG):
                LOG.error(
                    \'Run "bandit --debug %s" to see the full traceback.\', fname
                )

            self.skipped.append((fname, "exception while scanning file"))
            new_files_list.remove(fname)
            LOG.debug("  Exception string: %s", e)
            LOG.debug("  Exception traceback: %s", traceback.format_exc())
'''

new2 = '''    def _parse_file(
        self,
        fname,
        fdata,
        new_files_list,
        scan_scores=None,
        scan_cache_data=None,
    ):
        def _record_scan(skipped=False, skip_reason=None, score=None):
            if scan_cache_data is not None and fname != "<stdin>":
                scan_cache_data[fname] = {
                    "score": score,
                    "skipped": skipped,
                    "skip_reason": skip_reason,
                }

        try:
            # parse the current file
            data = fdata.read()
            lines = data.splitlines()
            self.metrics.begin(fname)
            self.metrics.count_locs(lines)
            # nosec_lines is a dict of line number -> set of tests to ignore
            #                                         for the line
            nosec_lines = dict()
            try:
                fdata.seek(0)
                tokens = tokenize.tokenize(fdata.readline)

                if not self.ignore_nosec:
                    for toktype, tokval, (lineno, _), _, _ in tokens:
                        if toktype == tokenize.COMMENT:
                            nosec_lines[lineno] = _parse_nosec_comment(tokval)

            except tokenize.TokenError:
                pass
            score = self._execute_ast_visitor(fname, fdata, data, nosec_lines)
            if scan_scores is not None:
                scan_scores[fname] = score
            _record_scan(score=score)
            self.metrics.count_issues([score])
        except KeyboardInterrupt:
            sys.exit(2)
        except SyntaxError:
            self.skipped.append(
                (fname, "syntax error while parsing AST from file")
            )
            new_files_list.remove(fname)
            _record_scan(
                skipped=True,
                skip_reason="syntax error while parsing AST from file",
            )
        except Exception as e:
            LOG.error(
                "Exception occurred when executing tests against %s.", fname
            )
            if not LOG.isEnabledFor(logging.DEBUG):
                LOG.error(
                    \'Run "bandit --debug %s" to see the full traceback.\', fname
                )

            self.skipped.append((fname, "exception while scanning file"))
            new_files_list.remove(fname)
            _record_scan(
                skipped=True, skip_reason="exception while scanning file"
            )
            LOG.debug("  Exception string: %s", e)
            LOG.debug("  Exception traceback: %s", traceback.format_exc())
'''

assert old2 in src, "_parse_file block not found"
src = src.replace(old2, new2, 1)

open(path, 'w').write(src)
PY
python -m py_compile bandit/core/manager.py && echo COMPILED