/* SPDX-License-Identifier: GPL-3.0-only */
/* Host harness diagnostic output only; never included by firmware. */
#ifndef FELUCCA_TEST_COVERAGE_REPORT_H
#define FELUCCA_TEST_COVERAGE_REPORT_H
static char coverage_path[4096];
static int coverage_begin(void)
{
    const char *path = getenv("FELUCCA_COVERAGE_CHILD");
    if (!path) return 0;
    if (strlen(path) >= sizeof coverage_path) return 1;
    strcpy(coverage_path, path);
    return unsetenv("FELUCCA_COVERAGE_CHILD") != 0;
}
static void coverage_string(FILE *f, const char *s)
{
    unsigned char c;
    fputc('"', f);
    while ((c = (unsigned char)*s++)) {
        if (c == '"' || c == '\\') { fputc('\\', f); fputc(c, f); }
        else if (c < 32) fprintf(f, "\\u%04x", c);
        else fputc(c, f);
    }
    fputc('"', f);
}
static int coverage_result(int failed, unsigned total, unsigned available, unsigned missing,
                           const char *baseline, const char *why)
{
    FILE *f;
    const char *status = "passed", *reason = "";
    if (!coverage_path[0]) return 0;
#ifdef C1_HOST
    status = "not_applicable"; reason = "c1-host-unqualified";
#else
    if (available != total) { status = "skipped"; reason = "counter-unavailable"; }
    else if (!strcmp(baseline, "-")) { status = "skipped"; reason = "baseline-unavailable"; }
#endif
    f = fopen(coverage_path, "w");
    if (!f) return 1;
    fprintf(f, "{\"schema\":1,\"outcomes\":[{\"name\":\"regression\",\"status\":\"%s\","
               "\"reason\":null,\"details\":{\"cpu_status\":", failed ? "failed" : "passed");
    coverage_string(f, status);
    fprintf(f, ",\"cpu_reason\":"); coverage_string(f, reason);
    fprintf(f, ",\"counter_detail\":"); coverage_string(f, why);
    fprintf(f, ",\"baseline\":"); coverage_string(f, baseline);
    fprintf(f, ",\"compiler\":"); coverage_string(f, __VERSION__);
    fprintf(f, ",\"total\":%u,\"available\":%u,\"missing_entries\":%u}}]}\n", total, available, missing);
    { int bad = ferror(f); return fclose(f) != 0 || bad; }
}
#endif
