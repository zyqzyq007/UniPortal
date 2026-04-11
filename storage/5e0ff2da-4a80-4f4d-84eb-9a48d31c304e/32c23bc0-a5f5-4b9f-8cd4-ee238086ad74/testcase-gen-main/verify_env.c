#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <zlib.h>

int main() {
    printf("Running Environment Check...\n");

    // Check 1: Math library
    double result = sqrt(16.0);
    if (result != 4.0) {
        fprintf(stderr, "Math check failed!\n");
        return 1;
    }
    printf("[PASS] Math library (sqrt(16) = %.2f)\n", result);

    // Check 2: Zlib library
    const char* version = zlibVersion();
    if (version == NULL) {
        fprintf(stderr, "Zlib check failed: version is NULL\n");
        return 1;
    }
    printf("[PASS] Zlib library (version: %s)\n", version);

    // Check 3: Standard IO and Memory (implicit)
    void* ptr = malloc(1024);
    if (ptr == NULL) {
        fprintf(stderr, "Memory allocation failed!\n");
        return 1;
    }
    free(ptr);
    printf("[PASS] Standard Lib & Memory Allocation\n");

    printf("Environment Check Complete: SUCCESS\n");
    return 0;
}
