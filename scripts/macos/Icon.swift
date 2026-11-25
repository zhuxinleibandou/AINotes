import AppKit

let size = 1024
let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)

func color(_ rgb: UInt32) -> NSColor {
    NSColor(srgbRed: CGFloat((rgb >> 16) & 255) / 255,
            green: CGFloat((rgb >> 8) & 255) / 255,
            blue: CGFloat(rgb & 255) / 255, alpha: 1)
}

func rounded(_ rect: NSRect, radius: CGFloat, fill: UInt32) {
    color(fill).setFill()
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).fill()
}

let tile = NSBezierPath(roundedRect: NSRect(x: 96, y: 96, width: 832, height: 832),
                        xRadius: 192, yRadius: 192)
let base = NSGradient(starting: color(0xF5A680), ending: color(0xB8553D))!
base.draw(in: tile, angle: -58)

rounded(NSRect(x: 278, y: 222, width: 424, height: 508), radius: 62, fill: 0x994333)
rounded(NSRect(x: 320, y: 270, width: 424, height: 508), radius: 62, fill: 0xFFF3DF)
rounded(NSRect(x: 390, y: 583, width: 255, height: 25), radius: 12, fill: 0xD88E70)
rounded(NSRect(x: 390, y: 516, width: 178, height: 25), radius: 12, fill: 0xD88E70)

let bookmark = NSBezierPath()
bookmark.move(to: NSPoint(x: 585, y: 778))
bookmark.line(to: NSPoint(x: 682, y: 778))
bookmark.line(to: NSPoint(x: 682, y: 661))
bookmark.line(to: NSPoint(x: 634, y: 688))
bookmark.line(to: NSPoint(x: 585, y: 661))
bookmark.close()
color(0xA44336).setFill()
bookmark.fill()

let spark = NSBezierPath()
spark.move(to: NSPoint(x: 654, y: 502))
spark.curve(to: NSPoint(x: 756, y: 400), controlPoint1: NSPoint(x: 674, y: 431), controlPoint2: NSPoint(x: 685, y: 420))
spark.curve(to: NSPoint(x: 654, y: 298), controlPoint1: NSPoint(x: 685, y: 380), controlPoint2: NSPoint(x: 674, y: 369))
spark.curve(to: NSPoint(x: 552, y: 400), controlPoint1: NSPoint(x: 634, y: 369), controlPoint2: NSPoint(x: 623, y: 380))
spark.curve(to: NSPoint(x: 654, y: 502), controlPoint1: NSPoint(x: 623, y: 420), controlPoint2: NSPoint(x: 634, y: 431))
spark.close()
color(0xB8553D).setFill()
spark.fill()

NSGraphicsContext.restoreGraphicsState()
try bitmap.representation(using: .png, properties: [:])!
    .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
