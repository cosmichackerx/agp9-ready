plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    id("org.jetbrains.kotlin.kapt")
    alias(libs.plugins.ksp)
}
android {
    namespace = "x.y"
    dexOptions { javaMaxHeapSize = "2g" }
    applicationVariants.all { println(name) }
    splits { density { isEnable = true } }
}
