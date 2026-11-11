// macOS built-in text recognition (Vision).  Usage: swift ocr.swift image.png  -> lines of "x0 y0 x1 y1 <tab> text" (fractions of the page, y from top)
import Foundation
import Vision
import AppKit
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { exit(1) }
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
req.recognitionLanguages = ["en-US"]
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
for obs in req.results ?? [] {
    guard let cand = obs.topCandidates(1).first else { continue }
    // word-level boxes
    let s = cand.string
    var idx = s.startIndex
    for word in s.split(separator: " ") {
        guard let r = s.range(of: word, range: idx..<s.endIndex), let box = try? cand.boundingBox(for: r) else { continue }
        idx = r.upperBound
        let b = box.boundingBox
        print(String(format: "%.4f %.4f %.4f %.4f\t%@", b.minX, 1 - b.maxY, b.maxX, 1 - b.minY, String(word)))
    }
}
