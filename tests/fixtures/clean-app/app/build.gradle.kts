plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.ksp)
}
android {
    namespace = "com.example.clean"
    compileSdk = 36
}
androidComponents {
    onVariants { variant -> println(variant.name) }
}
