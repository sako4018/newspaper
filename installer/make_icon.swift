// Рисува иконата на инсталатора (📰 върху светъл квадрат) в PNG 1024x1024.
// swift make_icon.swift icon.png   (вика се от build.sh)

import AppKit

let size = 1024.0
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
let rect = NSRect(x: 80, y: 80, width: size - 160, height: size - 160)
NSColor(calibratedRed: 0.96, green: 0.94, blue: 0.89, alpha: 1).setFill()
NSBezierPath(roundedRect: rect, xRadius: 180, yRadius: 180).fill()
let emoji = NSAttributedString(string: "📰", attributes: [.font: NSFont.systemFont(ofSize: 600)])
let s = emoji.size()
emoji.draw(at: NSPoint(x: (size - s.width) / 2, y: (size - s.height) / 2))
image.unlockFocus()

let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
let png = bitmap.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
