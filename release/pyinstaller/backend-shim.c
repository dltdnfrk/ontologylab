#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    uint32_t size = 0;
    _NSGetExecutablePath(NULL, &size);
    char *executable = malloc(size);
    if (executable == NULL || _NSGetExecutablePath(executable, &size) != 0) {
        fputs("backend_shim_refused member=executable\n", stderr);
        free(executable);
        return 70;
    }
    char *directory = dirname(executable);
    size_t length = strlen(directory) + strlen("/runtime/ontologylab-runtime") + 1;
    char *runtime = malloc(length);
    if (runtime == NULL) {
        fputs("backend_shim_refused member=allocation\n", stderr);
        free(executable);
        return 70;
    }
    snprintf(runtime, length, "%s/runtime/ontologylab-runtime", directory);
    execl(runtime, runtime, "desktop", NULL);
    perror("backend_shim_refused member=exec");
    free(runtime);
    free(executable);
    return 70;
}
